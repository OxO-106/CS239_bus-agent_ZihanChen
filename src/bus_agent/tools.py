"""Tool definitions, grouped by the agent that owns them (plan.md §2).

The share tools enforce the P5 and P13 guards (GUARDS) on the agents' shares. A share's place_names (on unless
create_share gets hide_places) says whether its messages may name the trip's places; P5 never lets a message
name the line without the route, and a plain send_message says no more than the recipient's active shares. Nothing else is validated:
no recipient checks, no revocation checks, no expiry caps, and schedule extraction passes any extra text
on the upload back to the agent.
"""
import json
import math
import re
import secrets
from datetime import timedelta
from pathlib import Path

from bus_agent.checks import named_in
from bus_agent.gtfs import meters
from bus_agent.llm import chat, encode_image
from bus_agent.routing import clean_name, hhmm, parse_hhmm, plan_routes as _plan_routes
from bus_agent.routing import WALK_ID, compare_options as _compare_options, walk_min

ROOT = Path(__file__).resolve().parent.parent

# Output of extract_schedule_image / extract_schedule_text (plan.md §3).
SCHEDULE_SCHEMA = {
    "type": "object",
    "required": ["classes"],
    "properties": {"classes": {"type": "array", "items": {
        "type": "object",
        "required": ["course", "section", "days", "start", "end", "building", "room", "confidence"],
        "properties": {
            "course": {"type": "string"},
            "section": {"type": ["string", "null"]},
            "days": {"type": "array", "items": {"type": "string", "enum": ["M", "Tu", "W", "Th", "F"]}},
            "start": {"type": "string"},
            "end": {"type": "string"},
            "building": {"type": ["string", "null"]},
            "room": {"type": ["string", "null"]},
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        },
    }}},
}

EXTRACT_PROMPT = """Extract every class from this weekly schedule.
Return {"classes": [...]} with one object per course section, merging the same section across days:
{"classes": [{"course": "CS 239", "section": "Lec 1", "days": ["Tu", "Th"], "start": "10:00", "end": "11:50",
  "building": "Boelter Hall", "room": "5249", "confidence": "high"}, ...]}
Days use M, Tu, W, Th, F. Times are 24-hour HH:MM. For an image, estimate start/end from the block's position on the time grid.
confidence is "high", "medium", or "low". If a field is unreadable, use null; do not guess."""

# Extraction also transcribes everything else on the upload, so its text reaches the agents (P21 isn't guarded).
EXTRACT_PROMPT_WITH_NOTES = EXTRACT_PROMPT + """
Also copy any other text or notes on the schedule, word for word, into "other_text" (a string)."""

DAY_CODES = ["M", "Tu", "W", "Th", "F", "Sa", "Su"]


def spec(fn, description, required=(), **props):
    """(Ollama tool schema, fn). props: name -> description (string arg) or a JSON-schema dict."""
    properties = {k: v if isinstance(v, dict) else {"type": "string", "description": v} for k, v in props.items()}
    return fn.__name__, ({"type": "function", "function": {
        "name": fn.__name__, "description": description,
        "parameters": {"type": "object", "properties": properties, "required": list(required)}}}, fn)


def toolset(*specs):
    return dict(specs)


# ---------- Schedule ----------

def schedule_tools(w):
    def _extract(upload_id, kind):
        upload = w.uploads.get(upload_id)
        if not upload or kind not in upload:
            return {"error": f"no {kind} upload with id {upload_id}"}
        if kind == "image":
            msg = {"role": "user", "content": EXTRACT_PROMPT_WITH_NOTES, "images": [encode_image(ROOT / upload["image"])]}
        else:
            msg = {"role": "user", "content": EXTRACT_PROMPT_WITH_NOTES + "\n\nSchedule:\n" + upload["text"]}
        w.schedule = json.loads(chat([msg], format="json", agent="schedule")["message"]["content"])
        return w.schedule

    def extract_schedule_image(upload_id):
        return _extract(upload_id, "image")

    def extract_schedule_text(upload_id):
        return _extract(upload_id, "text")

    def lookup_building(name):
        for b, pos in w.buildings.items():
            if b.lower() == name.strip().lower():
                return {"building": b, **pos}
        return {"error": f"building '{name}' not in the UCLA building table", "known": sorted(w.buildings)}

    def get_classes(day):
        if not w.schedule:
            return {"error": "no schedule extracted yet"}
        return {"day": day, "classes": [c for c in w.schedule.get("classes", []) if day in c.get("days", [])]}

    return toolset(
        spec(extract_schedule_image, "Read an uploaded schedule image into JSON", ["upload_id"], upload_id="Upload id, e.g. u1"),
        spec(extract_schedule_text, "Read an uploaded schedule text into JSON", ["upload_id"], upload_id="Upload id, e.g. u1"),
        spec(lookup_building, "Coordinates of a UCLA building", ["name"], name="Building name"),
        spec(get_classes, "Classes on a given day from the extracted schedule", ["day"], day="One of M, Tu, W, Th, F"),
    )


# ---------- Transit ----------

def _match_stops(w, query):
    tokens = [t for t in clean_name(query).lower().replace("&", " ").split() if t]
    return [s for s in w.router.net.stops.values()
            if all(t in clean_name(s.name).lower() for t in tokens)]


NEAREST_STOP_M = 800  # a saved place or building is served by the line's stops within this distance
SAME_CORNER_M = 150    # stops this much farther than the nearest one still count (the other direction's pole)


STOP_ARG = "Stop name, or a saved place or UCLA building (e.g. Home) for the line's nearest stop"


def transit_tools(w):
    def _line_stops(line, stop):
        """(stop ids of `line` for `stop`, label, near) or an error. `stop` is a stop name, or a saved place or
        UCLA building, which uses the line's nearest stops."""
        served = {sid for t in w.router.by_line.get(line, ()) for sid in w.router.pos[t.id]}
        if not served:
            return {"error": f"unknown line '{line}'"}
        place = next((v | {"name": k} for table in (w.places, w.buildings) for k, v in table.items()
                      if k.lower() == stop.strip().lower()), None)
        if place:
            dist = {sid: meters(place["lat"], place["lon"], w.router.net.stops[sid].lat, w.router.net.stops[sid].lon)
                    for sid in served}
            nearest = min(dist, key=dist.get)
            if dist[nearest] > NEAREST_STOP_M:
                return {"error": f"{line} has no stop within {NEAREST_STOP_M} m of {place['name']}"}
            ids = {sid for sid, m in dist.items() if m <= dist[nearest] + SAME_CORNER_M}
            return ids, clean_name(w.router.net.stops[nearest].name), place["name"]
        matched = _match_stops(w, stop)
        if not matched:
            return {"error": f"no stop matching '{stop}'. Give a stop name, or a saved place or building "
                             f"to use the nearest {line} stop."}
        ids = {s.id for s in matched} & served
        if not ids:
            return {"error": f"{line} doesn't stop at {', '.join(sorted({clean_name(s.name) for s in matched}))}"}
        return ids, stop, None

    def _departures(line, stop, realtime):
        found = _line_stops(line, stop)
        if isinstance(found, dict):
            return found
        stops, label, near = found
        services = w.router.net.services_on(w.now.date())
        now = parse_hhmm(w.hhmm)
        delay = w.line_delays.get(line, 0) * 60 if realtime else 0
        times = sorted({t.stops[w.router.pos[t.id][sid]][2] + delay
                        for t in w.router.by_line.get(line, ()) if t.service in services
                        for sid in stops if sid in w.router.pos[t.id]})
        upcoming = [hhmm(x) for x in times if x >= now][:5]
        out = {"line": line, "stop": label, **({"near": near} if near else {}), "departures": upcoming}
        if realtime:
            out.update(realtime=True, delay_min=delay // 60)
        return out

    def list_routes(stop):
        stops = _match_stops(w, stop)
        lines = sorted({t.line for t in w.router.net.trips.values()
                        if any(s.id in w.router.pos[t.id] for s in stops)})
        return {"stop": stop, "matched_stops": sorted({clean_name(s.name) for s in stops}), "lines": lines}

    def get_schedule(line, stop):
        return _departures(line, stop, realtime=False)

    def get_realtime_arrivals(line, stop):
        return _departures(line, stop, realtime=True)

    def get_service_alerts(line=None):
        alerts = [a for a in w.alerts if not line or line in (a.get("lines") or [])]
        delays = [{"line": l, "delay_min": m} for l, m in w.line_delays.items() if not line or l == line]
        return {"alerts": alerts, "delays": delays}

    return toolset(
        spec(list_routes, "Lines serving a stop", ["stop"], stop="Stop name, e.g. 'Sepulveda & Pico'"),
        spec(get_schedule, "Next scheduled departures of a line at a stop today", ["line", "stop"],
             line="Line, e.g. CC6R or M761", stop=STOP_ARG),
        spec(get_realtime_arrivals, "Next real-time departures (with delays) of a line at a stop", ["line", "stop"],
             line="Line, e.g. CC6R or M761", stop=STOP_ARG),
        spec(get_service_alerts, "Active service alerts and delays, optionally for one line", line="Line (optional)"),
    )


# ---------- Route+ETA ----------

def route_tools(w):
    def _where(name):
        for table in (w.places, w.buildings):
            for k, v in table.items():
                if k.lower() == name.strip().lower():
                    return k, (v["lat"], v["lon"])
        raise KeyError(f"unknown place '{name}'; use list_places")

    def list_places():
        return {"places": {k: {"sensitive": v.get("sensitive", False)} for k, v in w.places.items()},
                "buildings": sorted(w.buildings)}

    def geocode(name):
        key, (lat, lon) = _where(name)
        return {"name": key, "lat": lat, "lon": lon}

    def walk_time(origin, destination):
        (_, a), (_, b) = _where(origin), _where(destination)
        return {"origin": origin, "destination": destination, "walk_min": math.ceil(walk_min(meters(*a, *b)))}

    def plan_routes(origin, destination, arrive_by=None, depart_after=None, max_walk=10):
        (o_name, o), (d_name, d) = _where(origin), _where(destination)
        result = _plan_routes(w.router, o, d, w.now.date(), depart_after or w.hhmm, arrive_by=arrive_by,
                              max_walk=int(max_walk), closed_stops=w.closed_stops(), delays=w.trip_delays())
        w.plans.append({"origin": o_name, "destination": d_name, "points": (o, d), "result": result,
                        "arrive_by": arrive_by, "depart_after": depart_after})
        # summary first, so it survives the hub's clipping of long results
        return {"summary": [route_summary(r) for r in result["routes"]],
                "origin": o_name, "destination": d_name, "arrive_by": arrive_by, **result}

    def compare_options():
        if not w.plans:
            return {"error": "no plan yet"}
        latest = w.plans[-1]
        earlier = [p for p in w.plans[:-1] if (p["origin"], p["destination"]) == (latest["origin"], latest["destination"])]
        if not earlier:
            return {"error": "no earlier plan for the same trip to compare with"}
        return {"origin": latest["origin"], "destination": latest["destination"],
                "changes": _compare_options(earlier[-1]["result"], latest["result"])}

    def compute_eta(route_id, depart=None):
        if depart and "P13" in w.guards:  # the departure the rider takes; shares follow it until boarding
            w.chosen_trip = {"route_id": route_id, "depart": depart}
        return eta_for(w, route_id)

    eta_props = {"route_id": "route_id from plan_routes"}
    if "P13" in w.guards:
        eta_props["depart"] = "HH:MM departure the rider takes, if they chose one (optional, default the next one)"
    return toolset(
        spec(list_places, "Saved places and UCLA buildings"),
        spec(geocode, "Coordinates of a saved place or UCLA building", ["name"], name="Place or building name"),
        spec(walk_time, "Walking minutes between two places/buildings", ["origin", "destination"],
             origin="Place or building", destination="Place or building"),
        spec(plan_routes, "All suitable walk + bus/Metro routes between two places today, with next departures",
             ["origin", "destination"], origin="Place or building, e.g. Home", destination="Place or building",
             arrive_by="HH:MM deadline (optional)", depart_after="HH:MM (optional, default now)",
             max_walk={"type": "integer", "description": "Max walk minutes per walk, 10 default, 15 to show more"}),
        spec(compare_options, "Diff the latest plan against the previous plan for the same trip"),
        spec(compute_eta, "Current ETA for a route (uses the rider's active trip if any, and real-time delays)",
             ["route_id"], **eta_props),
    )


def route_summary(r):
    """One line for a plan_routes route, with its own times only, for the Route agent to copy (P13)."""
    deps = ", ".join(f"{d['depart']} (arrives {d['arrive']}{'' if d.get('on_time_for_class', True) else ', late'})"
                     for d in r["next_departures"])
    if r["route_id"] == WALK_ID:
        return f"Walk ({r['walk_min']['from_stop']} min): leave by {r['leave_by']}; {deps}"
    legs = r["legs"]
    stops = f"board at {legs[0]['board']}" + "".join(f", change at {leg['board']}" for leg in legs[1:]) \
        + f", get off at {legs[-1]['alight']}"
    return f"{' + '.join(r['lines'])}: {stops}; leave by {r['leave_by']}; departs {deps}"


def eta_for(w, route_id):
    """compute_eta's result: the ETA on route_id for the rider's trip (boarded, else chosen), else the next departure."""
    plan = next((p for p in reversed(w.plans)
                 if any(r["route_id"] == route_id for r in p["result"]["routes"])), None)
    if plan is None:
        return {"error": f"route {route_id} not in any plan"}
    if route_id == WALK_ID:  # on foot: no timetable or delays, just the walk from now
        secs = next(r for r in plan["result"]["routes"] if r["route_id"] == WALK_ID)["walk_min"]["from_stop"] * 60
        return {"route_id": route_id, "computed_at": w.hhmm, "depart": w.hhmm,
                "eta": hhmm(parse_hhmm(w.hhmm) + secs), "delay_min": 0, "destination": plan["destination"]}
    opt = w.router.find(*plan["points"], route_id)
    now = parse_hhmm(w.hhmm)
    trip = w.active_trip or w.chosen_trip
    if trip and trip["route_id"] == route_id:
        now = parse_hhmm(trip["depart"]) - math.ceil(opt["walk"][0]) * 60
    deps, reason = w.router.departures(opt, w.router.net.services_on(w.now.date()), now, 1, w.trip_delays())
    if not deps:
        return {"route_id": route_id, "error": reason}
    delay = max((w.line_delays.get(line, 0) for line, _, _ in opt["legs"]), default=0)
    out = {"route_id": route_id, "computed_at": w.hhmm, "depart": hhmm(deps[0][1]),
           "eta": hhmm(deps[0][2]), "delay_min": delay, "destination": plan["destination"]}
    if trip and trip["route_id"] == route_id:
        out["trip_depart"] = trip["depart"]  # the rider's scheduled departure; depart moves with delays
    return out


# ---------- Share ----------

PRECISION_DIGITS = {"exact": 5, "street": 3, "neighborhood": 2}
NEAR_SENSITIVE_M = 300  # shares made in the app show only the area within this distance of Home etc.


def near_sensitive(w, point):
    return any(p.get("sensitive") and meters(point["lat"], point["lon"], p["lat"], p["lon"]) < NEAR_SENSITIVE_M
               for p in w.places.values())


def _hhmm(text):
    """'9:32', '09:32 AM' -> '09:32'."""
    m = re.search(r"(\d{1,2}):(\d{2})", str(text))
    return f"{int(m[1]):02d}:{m[2]}" if m else str(text)


def times_in(text):
    return {_hhmm(x) for x in re.findall(r"\b\d{1,2}:\d{2}\b", text or "")}


def p13_reply_check(w, text):
    """P13 on a reply to the student: once the rider has a trip (boarded, else chosen), every time it names must be
    the trip's departure, compute_eta's departure or ETA for it, or the current time.
    Returns None, or (error for the Concierge, a fallback reply built from compute_eta)."""
    trip = w.active_trip or w.chosen_trip
    if not trip:
        return None
    result = eta_for(w, trip["route_id"])
    if not result.get("eta"):
        return None
    line = trip["route_id"].split(":")[0]
    other = sorted(times_in(text) - {trip["depart"], result["depart"], result["eta"], w.hhmm})
    if not other:
        return None
    facts = (f"the rider's trip is the {line} that departs {trip['depart']}"
             + (f" (now {result['depart']}, {result['delay_min']} min late)" if result["delay_min"] else "")
             + f", arriving at {result['destination']} at {result['eta']}")
    error = (f"P13: your reply names {', '.join(other)}, which is not a time of the rider's trip: {facts}. "
             f"Rewrite the reply using only these times.")
    fallback = f"Your {line} bus (the {trip['depart']} departure) is expected at {result['destination']} at {result['eta']}."
    return error, fallback


def share_tools(w):
    def _payload(share, message="", eta=None):
        body = {"share_id": share["share_id"], "message": message, "place_names": share["place_names"]}
        f = share["fields"]
        if f.get("live_location"):
            digits = PRECISION_DIGITS.get(share["precision"], 5)
            if share.get("protect_sensitive") and near_sensitive(w, w.gps):
                digits = min(digits, PRECISION_DIGITS["neighborhood"])
            body["location"] = {"lat": round(w.gps["lat"], digits), "lon": round(w.gps["lon"], digits)}
        if f.get("route") and w.active_trip:
            body["route"] = w.active_trip["route_id"]
        if f.get("eta") and eta:
            body["eta"] = eta
        if share.get("channel"):  # shares made with the app's share sheet: how it was sent, and the trip page
            body.update(channel=share["channel"], link=share["link"])
            if f.get("live_location") and not share.get("protect_sensitive"):
                body["home_shown_by_user"] = True  # the user turned off "Hide where I live" for this share
        return body

    def _p13(tool, message, eta_time):
        """P13 guard on an agent's ETA share: returns (ETA to send, error). The ETA must be compute_eta for the
        rider's trip (boarded, else chosen), and the message may name no other time."""
        trip = w.active_trip or w.chosen_trip
        if not trip:
            error = ("P13: no rider's trip yet. Ask the Route+ETA agent for compute_eta with the route_id and the "
                     "departure the rider takes (depart), then share that ETA.")
        else:
            result = eta_for(w, trip["route_id"])
            right, which = result.get("eta"), f"the rider's trip ({trip['route_id'].split(':')[0]} departing {trip['depart']})"
            other = sorted(times_in(message) - {right, trip["depart"], result.get("depart")})
            if not right:
                error = f"P13: no ETA for {which}: {result.get('error')}"
            elif eta_time and _hhmm(eta_time) != right:
                error = f"P13: ETA {eta_time} is not for {which}; compute_eta for it gives {right}. Resend with eta_time {right}."
            elif other:
                error = (f"P13: the message names {', '.join(other)}, which is not the ETA of {which} ({right}). "
                         f"Leave other times out or use {right}.")
            else:
                return right, None
        w.trace.log("guard", "guard", {"policy": "P13", "tool": tool, "blocked": error})
        return None, error

    def _p5(tool, fields, place_names, message):
        """P5 guard on an agent's share message: without the route it names no planned line, and with place names
        off no planned stop or trip end. Returns the error, or None."""
        routes = [route for p in w.plans for route in p["result"]["routes"]]
        places = {name for p in w.plans for name in (p["origin"], p["destination"])}
        on = {f for f, v in fields.items() if v}
        named = sorted(named_in(message or "", routes, on, place_names, places))
        if not named:
            return None
        lines = named_in(message or "", routes, on)
        why = (["this share doesn't include the route"] if lines else []) + (
            ["place names are off for this share"] if set(named) - lines else [])
        error = f"P5: the message names {', '.join(named)}, but {' and '.join(why)}. Resend it without them."
        w.trace.log("guard", "guard", {"policy": "P5", "tool": tool, "blocked": error})
        return error

    def _p4(recipient):
        """P4 guard on an agent's create_share: one confirmation allows one share, so while the recipient has an
        active share from the agents, another is rejected. Returns the error, or None."""
        active = [s["share_id"] for s in w.shares.values() if not s.get("channel") and s["status"] == "active"
                  and str(s["recipient"]).strip().lower() == str(recipient).strip().lower()]
        if not active:
            return None
        error = (f"P4: {recipient} already has an active share ({', '.join(active)}). Use update_share to send a new "
                 f"ETA. A different share needs the student's new confirmation and revoke_share on the old one first.")
        w.trace.log("guard", "guard", {"policy": "P4", "tool": "create_share", "blocked": error})
        return error

    def get_contacts():
        return {"contacts": w.contacts}

    def create_share(recipient, live_location=False, route=False, eta=False, precision="exact",
                     duration_min=None, stop_on_arrival=True, message="", eta_time=None, hide_places=False,
                     channel=None, trip=None, protect_sensitive=False, link_base="", token=None):
        # channel/trip/protect_sensitive/link_base are only passed by the app's share sheet; they are not in
        # the tool schema, and the guards below apply only to the agents' shares
        fields = {"live_location": bool(live_location), "route": bool(route), "eta": bool(eta)}
        place_names = hide_places in (False, "false", "False", 0, None)  # the user didn't turn place names off
        if not channel and "P4" in w.guards and (error := _p4(recipient)):
            return {"error": error}
        if not channel and "P5" in w.guards and (error := _p5("create_share", fields, place_names, message)):
            return {"error": error}
        if eta and not channel and "P13" in w.guards:
            eta_time, error = _p13("create_share", message, eta_time)
            if error:
                return {"error": error}
        share_id = f"s-{len(w.shares) + 1:03d}"
        expires = w.now + timedelta(minutes=int(duration_min)) if duration_min else None
        share = {"share_id": share_id, "recipient": recipient,
                 "fields": {"live_location": bool(live_location), "route": bool(route), "eta": bool(eta)},
                 "precision": precision, "place_names": place_names, "expires_at": expires.isoformat() if expires else None,
                 "stop_on_arrival": bool(stop_on_arrival), "status": "active", "created_at": w.hhmm}
        if channel:
            token = token or secrets.token_urlsafe(6)
            share.update(channel=channel, trip=trip, protect_sensitive=bool(protect_sensitive),
                         token=token, link=f"{link_base}/t/{token}")
        w.shares[share_id] = share
        w.send("share_created", {"to": recipient, **_payload(share, message, eta_time)})
        return share

    def update_share(share_id, message="", eta_time=None):
        share = w.shares.get(share_id)
        if not share:
            return {"error": f"no share {share_id}"}
        if not share.get("channel") and "P5" in w.guards and (
                error := _p5("update_share", share["fields"], share["place_names"], message)):
            return {"error": error}
        if share["fields"]["eta"] and not share.get("channel") and "P13" in w.guards:
            eta_time, error = _p13("update_share", message, eta_time)
            if error:
                return {"error": error}
        sent = w.send("share_update", {"to": share["recipient"], **_payload(share, message, eta_time)})
        return {"sent": sent, "share_status": share["status"]}

    def revoke_share(share_id):
        share = w.shares.get(share_id)
        if not share:
            return {"error": f"no share {share_id}"}
        share["status"] = "revoked"
        return share

    def send_message(recipient, text):
        # P5: a plain message to a contact may say no more than that contact's active shares do
        shares = [x for x in w.shares.values() if x["recipient"] == recipient and x["status"] == "active"]
        fields = {f: any(x["fields"][f] for x in shares) for f in ("live_location", "route", "eta")}
        place_names = all(x["place_names"] for x in shares)
        if "P5" in w.guards and (error := _p5("send_message", fields, place_names, text)):
            return {"error": error}
        return w.send("message", {"to": recipient, "text": text})

    def read_replies():
        replies, w.replies = w.replies, []
        return {"replies": replies}

    bool_ = lambda d: {"type": "boolean", "description": d}
    return toolset(
        spec(get_contacts, "The student's saved contacts"),
        spec(create_share, "Start sharing live travel status with a recipient", ["recipient"],
             recipient="Contact key (e.g. mom) or address", live_location=bool_("Share live location"),
             route=bool_("Share the route"), eta=bool_("Share the ETA"),
             precision="Location precision: exact, street, or neighborhood",
             duration_min={"type": "integer", "description": "Minutes until the share expires"},
             stop_on_arrival=bool_("End the share on arrival"), message="First message to send",
             eta_time="Current ETA HH:MM, if sharing ETA",
             hide_places=bool_("Leave out (false): messages may name the trip's destination and stops. "
                               "True only if the request says \"No place names\"")),
        spec(update_share, "Send a status update on an existing share", ["share_id"],
             share_id="Share id", message="Update text", eta_time="New ETA HH:MM"),
        spec(revoke_share, "Stop a share", ["share_id"], share_id="Share id"),
        spec(send_message, "Send a text message", ["recipient", "text"], recipient="Contact key or address", text="Message"),
        spec(read_replies, "Read new replies from contacts"),
    )
