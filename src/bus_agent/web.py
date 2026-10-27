"""Local web app: chat with the Concierge, a map of the routes it shows, shares, and the agents at work.

python -m bus_agent.web [--port 8239]  ->  http://localhost:8239

One session at a time. Live mode is a chat (with schedule upload) on the real clock. Scenario mode
steps through a scenarios/*.json timeline; scripted answers are used for ask_user when the scenario
has them, otherwise the question waits for you in the chat. The page gets updates over SSE.
Uses the placeholder Home only, and saves traces to data/local/traces/ (untracked).
"""
import argparse
import json
import math
import queue
import re
import secrets
import threading
import uuid
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from bus_agent import gtfs
from bus_agent.agents import build
from bus_agent.bus import Bus
from bus_agent.checks import mentions, run_checks
from bus_agent.gtfs import meters
from bus_agent.main import _uploads
from bus_agent.routing import WALK_ID, Router, _short, clean_name, hhmm, parse_hhmm, walk_min
from bus_agent.tools import DAY_CODES, near_sensitive, route_tools, schedule_tools, share_tools
from bus_agent.trace import Trace
from bus_agent.world import World

ROOT = Path(__file__).resolve().parent.parent
PAGE = Path(__file__).resolve().parent / "static" / "index.html"
RECIPIENT_PAGE = Path(__file__).resolve().parent / "static" / "recipient.html"
PROFILE = json.loads((ROOT / "data/mock/profile.json").read_text())

# share sheet choices -> share settings
PRECISION = {"exact": "exact", "street": "street", "area": "neighborhood"}
DURATION_MIN = {"arrive": None, "30": 30, "60": 60, "120": 120}
MAX_SHARE_MIN = 240                                  # every share stops within 4 hours
RADIUS_M = {"exact": 25, "street": 150, "neighborhood": 800}  # how big the recipient's location circle is
UPLOADS = ROOT / "data/local/uploads"
TRACES = ROOT / "data/local/traces"


# ---------- map geometry ----------

def route_geometry(router, route_id, origin=None, dest=None, shapes=None):
    """Polylines for a route_id: [{"kind": "walk" | "bus" | "rail", "line", "coords": [[lat, lon]]}].

    Rides follow the trip's GTFS shape when `shapes` has it, otherwise straight lines between stops."""
    if route_id == WALK_ID:
        return ({"route_id": route_id, "lines": ["Walk"], "parts": [{"kind": "walk", "coords": [list(origin), list(dest)]}]}
                if origin and dest else None)
    parts, prev = [], origin
    for leg in route_id.split("|"):
        line, stops = leg.split(":", 1)
        board, alight = stops.split(">")
        coords = _ride(router, line, board, alight, shapes or {})
        if not coords:
            return None
        if prev:
            parts.append({"kind": "walk", "coords": [list(prev), coords[0]]})
        parts.append({"kind": router.net.lines.get(line, "bus"), "line": line, "coords": coords,
                      "board": _stop_name(router, line, board), "alight": _stop_name(router, line, alight)})
        prev = coords[-1]
    if dest:
        parts.append({"kind": "walk", "coords": [prev, list(dest)]})
    return {"route_id": route_id, "lines": [p["line"] for p in parts if "line" in p], "parts": parts}


def _ride(router, line, board, alight, shapes):
    """Path from board to alight on the first trip pattern of `line` that serves both."""
    for stops, trip in router.patterns.get(line, {}).items():
        names = [_short(router.net.stops[s].name) for s in stops]
        if board in names and alight in names[names.index(board) + 1:]:
            i = names.index(board)
            j = names.index(alight, i + 1)
            pts = [[router.net.stops[s].lat, router.net.stops[s].lon] for s in stops[i:j + 1]]
            shape = shapes.get(trip.shape)
            if shape:
                a = _nearest(shape, pts[0], 0)
                b = _nearest(shape, pts[-1], a)
                if b > a:
                    return [pts[0]] + [list(p) for p in shape[a:b + 1]] + [pts[-1]]
            return pts
    return None


def _nearest(shape, point, start):
    return min(range(start, len(shape)), key=lambda k: meters(*shape[k], *point))


def _stop_name(router, line, short):
    for stops in router.patterns.get(line, {}):
        for s in stops:
            if _short(router.net.stops[s].name) == short:
                return clean_name(router.net.stops[s].name)
    return short


# ---------- session ----------

class Session:
    def __init__(self, router, scenario_path=None, broadcast=lambda item: None, shapes=None):
        self.router = router
        self.shapes = shapes or {}
        self.broadcast = broadcast
        self.feed = []                     # everything sent to the page, replayed on reconnect
        self.lock = threading.Lock()
        self.busy = False
        self.question = None               # an ask_user question waiting for the page
        self.answers = queue.Queue()
        self.map = {"shown": [], "others": [], "found": 0, "active": None, "origin": None, "dest": None,
                    "source": None, "query": None}
        self.review = None                 # extracted classes waiting for the user to confirm
        self.schedule_confirmed = False
        self.sc = json.loads(Path(scenario_path).read_text()) if scenario_path else None
        self.file = Path(scenario_path).name if scenario_path else None
        self.step_i = 0
        start = self.sc["start"] if self.sc else datetime.now().isoformat(timespec="minutes")
        header = ({"scenario": self.sc["id"], "title": self.sc["title"], "expected": self.sc["expected"],
                   "requirements": self.sc.get("requirements", []), "uploads": self.sc.get("uploads", {})}
                  if self.sc else {"scenario": "web", "title": "web session"})
        header.update(recorded=datetime.now().isoformat(timespec="seconds"), app="web",
                      specialist_replies="summary + raw tool results")
        self.trace = Trace(header)
        self.world = World(router, start, self.trace, _uploads(self.sc.get("uploads")) if self.sc else {})
        self.trace.clock = lambda: self.world.hhmm
        self.trace.listeners.append(self._on_event)
        self.concierge = build(self.world, Bus(self.trace, lambda: self.world.hhmm), self.trace, self._ask_user)
        self.tools = {**route_tools(self.world), **schedule_tools(self.world), **share_tools(self.world)}  # page buttons
        self.link_base = ""                # http://host:port, set by the server for share links
        self._push_state()

    # page updates
    def _emit(self, item):
        with self.lock:
            self.feed.append(item)
        self.broadcast(item)

    def _on_event(self, e):
        self._emit({"type": "trace", "event": e})
        if e["kind"] == "message" and e["agent"] == "concierge" and e["data"]["to"] == "user":
            self._update_shown(e["data"]["text"])
        elif e["kind"] == "event" and e["data"].get("type") == "board":
            self.map["active"] = route_geometry(self.router, e["data"]["route_id"], shapes=self.shapes)
            self._emit({"type": "map", **self.map})
        elif e["kind"] == "event" and e["data"].get("type") == "arrive":
            self.map["active"] = None
            self._emit({"type": "map", **self.map})
        if e["kind"] in ("outbox", "event") or (e["kind"] == "tool_result" and e["data"]["name"] in (
                "extract_schedule_image", "extract_schedule_text", "plan_routes")):  # side panels changed
            self._push_state()

    def _update_shown(self, reply):
        """After a chat reply: send the latest plan, marking the routes the Concierge's reply mentions."""
        if not self.world.plans:
            return
        routes = self.world.plans[-1]["result"]["routes"]
        shown = [r for r in routes if all(mentions(reply, line) for line in r["lines"])]
        if shown:
            self._publish_plan("chat", shown)

    def _publish_plan(self, source, shown=None):
        """Send the latest plan to the page. source "chat": `shown` are the routes the reply mentions (the rest
        are tagged "Not in chat"); source "planner": the user asked with the Directions panel, so all are shown."""
        plan = self.world.plans[-1]
        routes = plan["result"]["routes"]
        origin, dest = plan["points"]
        geo = [(r, route_geometry(self.router, r["route_id"], origin, dest, self.shapes)) for r in routes]
        drawn = [{**g, "labels": r["labels"], "next_departures": r["next_departures"], "walk_min": r["walk_min"],
                  "leave_by": r["leave_by"], "in_chat": shown is None or r in shown}
                 for r, g in geo if g]
        self.map.update(origin=list(origin), dest=list(dest), found=len(routes), source=source,
                        query={k: plan.get(k) for k in ("origin", "destination", "arrive_by", "depart_after")},
                        shown=[d for d in drawn if d["in_chat"]], others=[d for d in drawn if not d["in_chat"]])
        self._emit({"type": "map", **self.map})

    def state(self):
        w = self.world
        courses = [c["course"] for c in (w.schedule or {}).get("classes", [])] or (self.sc or {}).get("courses", [])
        checks = run_checks(self.trace.events, w.contacts, (self.sc or {}).get("approved_fields"), courses, w.places)
        return {"type": "state", "time": w.hhmm, "day": w.now.strftime("%a %b %d"), "gps": w.gps,
                "busy": self.busy, "question": self.question, "next": self._next_label(),
                "scenario": {**{k: self.sc[k] for k in ("id", "title", "expected")}, "file": self.file} if self.sc else None,
                "today": self._today(), "shares": list(w.shares.values()), "outbox": w.outbox, "checks": checks,
                "schedule": {"confirmed": self.schedule_confirmed, "review": self.review,
                             "classes": (w.schedule or {}).get("classes")},
                "contacts": {k: {"name": c["name"], "trusted": c.get("trusted", False), "email": c.get("email"),
                                 "phone": c["channel"].removeprefix("sms:") if c.get("channel", "").startswith("sms:") else None}
                             for k, c in w.contacts.items()}}

    def _today(self):
        """Today's classes from the extracted schedule, with the next one's leave-by from the latest plan to it."""
        w = self.world
        if not w.schedule:
            return {"date": w.now.strftime("%a, %b %d"), "classes": None, "confirmed": False}
        code = DAY_CODES[w.now.weekday()]
        classes = sorted((c for c in w.schedule.get("classes", []) if code in (c.get("days") or [])),
                         key=lambda c: c.get("start") or "")
        out, prev = [], None
        for c in classes:
            item = {k: c.get(k) for k in ("course", "start", "end", "building", "room")}
            here = w.buildings.get(c.get("building") or "")
            if prev and here:
                item["walk_from_prev"] = {"from": prev[0], "min": math.ceil(walk_min(meters(*prev[1], here["lat"], here["lon"])))}
            prev = (c.get("building"), (here["lat"], here["lon"])) if here else None
            out.append(item)
        nxt = next((c for c in out if (c["end"] or "") > w.hhmm), None)
        if nxt:
            nxt["next"] = True
            plan = next((p for p in reversed(w.plans) if p["destination"] == nxt["building"]), None)
            if plan:  # the latest departure the rider can still make that arrives by class start
                catchable = [(d["arrive"], hhmm(parse_hhmm(d["depart"]) - r["walk_min"]["to_stop"] * 60), r["lines"])
                             for r in plan["result"]["routes"] for d in r["next_departures"]
                             if parse_hhmm(d["depart"]) - r["walk_min"]["to_stop"] * 60 >= parse_hhmm(w.hhmm)]
                in_time = [c for c in catchable if nxt["start"] and c[0] <= nxt["start"]]
                if in_time or catchable:
                    _, leave, lines = max(in_time, key=lambda c: c[1]) if in_time else min(catchable)
                    nxt["leave_by"] = {"time": leave, "lines": lines}
        return {"date": w.now.strftime("%a, %b %d"), "classes": out, "confirmed": self.schedule_confirmed}

    def _push_state(self):
        self._emit(self.state())

    def _next_label(self):
        if not self.sc or self.step_i >= len(self.sc["events"]):
            return None
        e = self.sc["events"][self.step_i]
        text = {"user": lambda: f"You: \"{e['text']}\"",
                "delay": lambda: f"{e['line']} running {e['minutes']} min late",
                "alert": lambda: f"Service alert: {e['text']}",
                "gps": lambda: "Rider moves",
                "board": lambda: f"Rider boards {e['route_id'].split(':')[0]} at {e['depart']}",
                "reply": lambda: f"{self.world.contacts.get(e['from'], {}).get('name', e['from'])} replies: \"{e['text']}\"",
                "arrive": lambda: f"Rider arrives at {e['place']}"}[e["type"]]()
        return {"at": e["at"], "text": text, "n": self.step_i + 1, "of": len(self.sc["events"])}

    # actions (each runs in a worker thread so the page stays responsive)
    def _run(self, fn):
        if self.busy:
            return False
        self.busy = True
        self._push_state()

        def work():
            try:
                fn()
            except Exception as e:  # show model/tool failures in the chat instead of hanging the page
                self._emit({"type": "error", "text": f"{type(e).__name__}: {e}"})
            finally:
                self.busy = False
                self._push_state()
        threading.Thread(target=work, daemon=True).start()
        return True

    def message(self, text):
        if self.question is not None:   # the Concierge is waiting on ask_user
            self.answers.put(text)
            return True
        def go():
            if not self.sc:
                self.world.now = datetime.now()
            self.trace.log("user", "message", {"to": "concierge", "text": text})
            reply = self.concierge.run(f"[{self.world.hhmm}] {text}")
            self.trace.log("concierge", "message", {"to": "user", "text": reply})
        return self._run(go)

    def step(self):
        if self.busy or not self.sc or self.step_i >= len(self.sc["events"]):
            return False
        event = self.sc["events"][self.step_i]
        self.step_i += 1

        def go():
            w = self.world
            w.set_time(event["at"])
            if event["type"] == "user":
                w.user_replies = list(event.get("replies", []))
                self.trace.log("user", "message", {"to": "concierge", "text": event["text"]})
                reply = self.concierge.run(f"[{w.hhmm}] {event['text']}")
                self.trace.log("concierge", "message", {"to": "user", "text": reply})
                w.user_replies = []
            else:
                w.apply(event)
                self._after_world_event(event)
                if event.get("notify"):
                    self.trace.log("system", "message", {"to": "concierge", "text": event["notify"]})
                    reply = self.concierge.run(f"[{w.hhmm}] (system notice) {event['notify']}")
                    self.trace.log("concierge", "message", {"to": "user", "text": reply})
        return self._run(go)

    def upload(self, filename, data):
        suffix = Path(filename).suffix.lower()
        uid = f"u{len(self.world.uploads) + 1}"
        if suffix in (".png", ".jpg", ".jpeg"):
            UPLOADS.mkdir(parents=True, exist_ok=True)
            path = UPLOADS / f"{uuid.uuid4().hex}{suffix}"
            path.write_bytes(data)
            self.world.uploads[uid] = {"image": str(path)}
            kind = "image"
        else:
            self.world.uploads[uid] = {"text": data.decode("utf-8", errors="replace")}
            kind = "text file"
        return self.message(f"I uploaded my class schedule as an {kind} (upload {uid}). Can you read it?")

    # the page's own buttons: they call the same tools the agents use, logged as the user's actions

    def _tool(self, name, **args):
        self.trace.log("app", "tool_call", {"name": name, "arguments": args})
        try:
            result = self.tools[name][1](**args)
        except Exception as e:  # e.g. an unknown place name
            result = {"error": f"{type(e).__name__}: {e}"}
        self.trace.log("app", "tool_result", {"name": name, "result": result})
        return result

    def plan(self, origin, destination, mode="arrive", time=None):
        """Directions panel: plan routes now, without the chat. mode: "arrive" (by time), "depart" (at time), "now"."""
        if self.busy:
            return {"error": "still working on the last request"}
        if not self.sc:
            self.world.now = datetime.now()
        args = {"origin": origin, "destination": destination}
        if mode == "arrive" and time:
            args["arrive_by"] = time
        elif mode == "depart" and time:
            args["depart_after"] = time
        self.trace.log("user", "action", {"action": "plan", **args})
        result = self._tool("plan_routes", **args)
        if "error" in result:
            return result
        self._publish_plan("planner")
        self._push_state()
        return {"ok": True, "count": result["count"]}

    def schedule_upload(self, filename, data):
        """Upload button: read the schedule with the extractor, then hold it for the user to review."""
        suffix = Path(filename).suffix.lower()
        uid = f"u{len(self.world.uploads) + 1}"
        if suffix in (".png", ".jpg", ".jpeg"):
            UPLOADS.mkdir(parents=True, exist_ok=True)
            path = UPLOADS / f"{uuid.uuid4().hex}{suffix}"
            path.write_bytes(data)
            self.world.uploads[uid] = {"image": str(path)}
            tool = "extract_schedule_image"
        else:
            self.world.uploads[uid] = {"text": data.decode("utf-8", errors="replace")}
            tool = "extract_schedule_text"

        def go():
            self.trace.log("user", "action", {"action": "upload_schedule", "upload_id": uid, "file": Path(filename).name})
            result = self._tool(tool, upload_id=uid)
            if "error" in result:
                raise ValueError(result["error"])
            self.review = result.get("classes", [])
            self.schedule_confirmed = False
        return self._run(go)

    def schedule_confirm(self, classes):
        """The user checked (and maybe edited) the schedule: use it from now on."""
        self.world.schedule = {"classes": classes}
        self.review = None
        self.schedule_confirmed = True
        self.trace.log("user", "action", {"action": "confirm_schedule", "classes": classes})
        self._push_state()
        return {"ok": True}

    def schedule_cancel(self):
        """Close the review without changing the schedule."""
        self.review = None
        self._push_state()
        return {"ok": True}

    def schedule_review(self):
        """Reopen the current schedule for review (e.g. after the chat read it)."""
        self.review = (self.world.schedule or {}).get("classes", [])
        self._push_state()
        return {"ok": True}

    # ---------- sharing from the share sheet ----------

    def _trip(self, route_id, depart=None):
        """The planned trip a share is about: a route of a plan and one of its departures."""
        for plan in reversed(self.world.plans):
            for r in plan["result"]["routes"]:
                if r["route_id"] == route_id:
                    d = next((d for d in r["next_departures"] if d["depart"] == depart), r["next_departures"][0])
                    return {"route_id": route_id, "lines": r["lines"], "depart": d["depart"], "arrive": d["arrive"],
                            "destination": plan["destination"]}
        return None

    def _share_message(self, who, opts, trip, link):
        """The text or email the recipient gets (also the share sheet's preview)."""
        name, f = PROFILE["name"], opts.get("fields", {})
        sees = [label for key, label in (("eta", "arrival time"), ("live_location", {
            "exact": "exact location", "street": "street-level location", "area": "approximate area"}[opts.get("precision", "area")]),
            ("route", "bus")) if f.get(key)]
        minutes = DURATION_MIN.get(opts.get("duration", "arrive"))
        ends = (f"when {name} arrives" if minutes is None else f"in {minutes} min" if minutes < 60
                else f"in {minutes // 60} hour{'s' if minutes > 60 else ''}")
        eta = f", arriving around {trip['arrive']}" if trip and f.get("eta") else ""
        lead = f"{name} is on the way to {trip['destination']}{eta}." if trip else f"{name} is sharing their trip with you."
        channel = opts.get("channel", "text")
        if channel == "email":
            return {"subject": f"{name} is sharing their trip with you", "sees": sees,
                    "text": f"Hi {who},\n{lead}\nFollow the trip: {link}\nYou'll see {name}'s {_and(sees) or 'nothing yet'}. "
                            f"Sharing ends {ends}."}
        if channel == "link":
            return {"sees": sees, "text": f"{link}\nAnyone with this link sees {_and(sees) or 'nothing'} until sharing ends {ends}."}
        return {"sees": sees, "text": f"{lead} Follow along: {link}\n(Sharing ends {ends}.)"}

    def share_preview(self, opts):
        who = self.world.contacts.get(opts.get("recipient"), {}).get("name", "")
        trip = self._trip(opts["trip"]["route_id"], opts["trip"].get("depart")) if opts.get("trip") else None
        return self._share_message(who, opts, trip, f"{self.link_base}/t/…")

    def share(self, opts):
        """Share sheet: who, what, how long, sent how. Only trusted contacts; at most 4 hours.

        hide_home (default on) blurs the location to the area near Home; off shows it at the chosen precision."""
        w = self.world
        contact = w.contacts.get(opts.get("recipient"))
        if not contact or not contact.get("trusted"):
            return {"error": "Only trusted contacts can be shared with. Add them to your trusted contacts first."}
        channel = opts.get("channel", "text")
        if channel == "email" and not contact.get("email"):
            return {"error": f"No email address for {contact['name']}."}
        if opts.get("duration", "arrive") not in DURATION_MIN:
            return {"error": "Unknown duration."}
        f = opts.get("fields", {})
        trip = self._trip(opts["trip"]["route_id"], opts["trip"].get("depart")) if opts.get("trip") else None
        token = secrets.token_urlsafe(6)
        link = f"{self.link_base}/t/{token}"
        msg = self._share_message(contact["name"], opts, trip, link)
        self.trace.log("user", "action", {"action": "share", **{k: opts.get(k) for k in ("recipient", "fields", "precision",
                                                                                           "hide_home", "duration", "channel")},
                                          "trip": trip})
        result = self._tool("create_share", recipient=opts["recipient"], live_location=bool(f.get("live_location")),
                            route=bool(f.get("route")), eta=bool(f.get("eta")),
                            precision=PRECISION.get(opts.get("precision", "area"), "neighborhood"),
                            duration_min=DURATION_MIN[opts.get("duration", "arrive")] or MAX_SHARE_MIN,
                            stop_on_arrival=True, message=msg["text"], eta_time=trip["arrive"] if trip and f.get("eta") else None,
                            channel=channel, trip=trip, protect_sensitive=bool(opts.get("hide_home", True)),
                            link_base=self.link_base, token=token)
        if "error" in result:
            return result
        if msg.get("subject"):
            w.outbox[-1]["subject"] = msg["subject"]
        self._push_state()
        return {"ok": True, "share_id": result["share_id"], "link": result["link"]}

    def share_stop(self, share_id):
        share = self.world.shares.get(share_id)
        if not share:
            return {"error": "No such share."}
        self.trace.log("user", "action", {"action": "stop_share", "share_id": share_id})
        self._tool("revoke_share", share_id=share_id)
        if share.get("channel") in ("text", "email"):
            self.world.send("message", {"to": share["recipient"], "channel": share["channel"], "share_id": share_id,
                                        "text": f"{PROFILE['name']} stopped sharing their trip."})
        self._push_state()
        return {"ok": True}

    def _after_world_event(self, event):
        """Keep app-made shares current: new ETA once aboard and after delays, end on arrival or expiry."""
        w, name = self.world, PROFILE["name"]
        for share in list(w.shares.values()):
            if not share.get("channel"):
                continue  # shares made by the agents are left to the agents (Phase 1)
            trip = share.get("trip") or {}
            if share["status"] == "ended" and "ended_at" not in share:
                share["ended_at"] = w.hhmm
                if share["channel"] != "link":
                    w.send("message", {"to": share["recipient"], "channel": share["channel"], "share_id": share["share_id"],
                                       "text": f"{name} arrived at {trip.get('destination', 'their destination')}. Sharing has ended."})
            elif share["status"] == "active" and share["expires_at"] and w.now.isoformat() >= share["expires_at"]:
                share.update(status="expired", ended_at=w.hhmm)
                if share["channel"] != "link":
                    w.send("message", {"to": share["recipient"], "channel": share["channel"], "share_id": share["share_id"],
                                       "text": f"{name}'s trip sharing has ended."})
            elif (share["status"] == "active" and share["fields"]["eta"] and event["type"] in ("board", "delay")
                  and w.active_trip and w.active_trip["route_id"] == trip.get("route_id")):
                eta = self._tool("compute_eta", route_id=trip["route_id"]).get("eta")
                if eta and eta != self._last_eta(share):
                    late = max((w.line_delays.get(l, 0) for l in trip.get("lines", [])), default=0)
                    text = (f"Update: {name}'s bus is running {late} min late. New arrival around {eta}." if late
                            else f"Update: {name} is on the bus, arriving around {eta}.")
                    self._tool("update_share", share_id=share["share_id"], message=text, eta_time=eta)

    def _last_eta(self, share):
        sent = [o for o in self.world.outbox if o.get("share_id") == share["share_id"] and o.get("eta")]
        return sent[-1]["eta"] if sent else None

    def recipient_view(self, token):
        """What the person a trip was shared with sees: only the fields that were chosen, only while it's live."""
        w = self.world
        share = next((x for x in w.shares.values() if x.get("token") == token), None)
        if not share:
            return None
        if not self.sc:
            w.now = datetime.now()
        if share["status"] == "active" and share["expires_at"] and w.now.isoformat() >= share["expires_at"]:
            share.update(status="expired", ended_at=w.hhmm)
        trip = share.get("trip") or {}
        dest = w.buildings.get(trip.get("destination")) or w.places.get(trip.get("destination"))
        view = {"status": share["status"], "name": PROFILE["name"], "destination": trip.get("destination"),
                "ended_at": share.get("ended_at"), "started": share["created_at"], "now": w.hhmm,
                "ends": "arrival" if share["expires_at"] is None or share.get("stop_on_arrival") else share["expires_at"][11:16],
                "fields": share["fields"]}
        if share["status"] != "active":
            return view  # nothing live after sharing ends
        sent = [o for o in w.outbox if o.get("share_id") == share["share_id"]]
        view["updated"] = sent[-1]["at"] if sent else share["created_at"]
        if share["fields"]["eta"]:
            view["eta"] = self._last_eta(share)
            view["late_min"] = max((w.line_delays.get(l, 0) for l in trip.get("lines", [])), default=0)
        if share["fields"]["live_location"]:
            precision = share["precision"]
            if share.get("protect_sensitive") and near_sensitive(w, w.gps):
                precision = "neighborhood"
            digits = {"exact": 5, "street": 3, "neighborhood": 2}.get(precision, 2)
            view["location"] = {"lat": round(w.gps["lat"], digits), "lon": round(w.gps["lon"], digits),
                                "radius_m": RADIUS_M.get(precision, 800)}
        if share["fields"]["route"] and trip:
            view["lines"] = trip["lines"]
        if dest:
            view["dest_point"] = [dest["lat"], dest["lon"]]
        view["on_board"] = bool(w.active_trip)
        return view

    def _ask_user(self, question):
        self.trace.log("concierge", "message", {"to": "user", "text": question})
        if self.world.user_replies:
            answer = self.world.user_replies.pop(0)
        else:
            self.question = question
            self._push_state()
            answer = self.answers.get()
            self.question = None
        self.trace.log("user", "message", {"to": "concierge", "text": answer})
        return {"answer": answer}

    def save(self):
        stem = f"{self.trace.header['scenario']}-web-{datetime.now():%Y%m%d-%H%M%S}"
        self.trace.header["checks"] = self.state()["checks"]
        return self.trace.save(TRACES, stem)


# ---------- HTTP ----------

class App:
    def __init__(self, router, shapes=None):
        self.router = router
        self.shapes = shapes or {}
        self.clients = []
        self.clients_lock = threading.Lock()
        self.session = Session(router, broadcast=self.broadcast, shapes=self.shapes)

    def broadcast(self, item):
        with self.clients_lock:
            for q in self.clients:
                q.put(item)

    def init(self):
        scenarios = [{"file": p.name, **{k: json.loads(p.read_text())[k] for k in ("id", "title")}}
                     for p in sorted((ROOT / "scenarios").glob("*.json"), key=lambda p: _natural(p.stem))]
        w = self.session.world
        return {"scenarios": scenarios, "places": w.places, "buildings": w.buildings}

    def new_session(self, scenario_file):
        path = None
        if scenario_file:
            path = ROOT / "scenarios" / Path(scenario_file).name
            if not path.exists():
                raise FileNotFoundError(scenario_file)
        old = self.session
        old.broadcast = lambda item: None  # a run still in progress keeps going, but off-screen
        if old.question is not None:
            old.answers.put("(session ended)")
        self.broadcast({"type": "reset"})
        self.session = Session(self.router, path, broadcast=self.broadcast, shapes=self.shapes)


def _and(items):
    """["a", "b", "c"] -> "a, b and c"."""
    return ", ".join(items[:-1]) + " and " + items[-1] if len(items) > 1 else "".join(items)


def _natural(text):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", text)]


def handler(app):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _json(self, obj, status=200):
            body = json.dumps(obj, ensure_ascii=False, default=str).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/":
                body = PAGE.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path == "/api/init":
                self._json(app.init())
            elif re.fullmatch(r"/t/[\w-]{4,20}", self.path):
                body = RECIPIENT_PAGE.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif re.fullmatch(r"/api/t/[\w-]{4,20}", self.path):
                view = app.session.recipient_view(self.path.rsplit("/", 1)[1])
                self._json(view or {"status": "unknown"}, 200 if view else 404)
            elif self.path == "/api/events":
                self._events()
            else:
                self._json({"error": "not found"}, 404)

        def _events(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            q = queue.Queue()
            with app.clients_lock:
                app.clients.append(q)
                backlog = list(app.session.feed)
            try:
                for item in [{"type": "reset"}] + backlog:
                    self._send(item)
                while True:
                    try:
                        self._send(q.get(timeout=15))
                    except queue.Empty:
                        self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass
            finally:
                with app.clients_lock:
                    app.clients.remove(q)

        def _send(self, item):
            self.wfile.write(f"data: {json.dumps(item, ensure_ascii=False, default=str)}\n\n".encode())
            self.wfile.flush()

        def do_POST(self):
            size = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(size)
            s = app.session
            try:
                if self.path == "/api/session":
                    app.new_session(json.loads(body or b"{}").get("scenario"))
                    self._json({"ok": True})
                elif self.path == "/api/message":
                    self._json({"ok": s.message(json.loads(body)["text"])})
                elif self.path == "/api/step":
                    self._json({"ok": s.step()})
                elif self.path in ("/api/share/preview", "/api/share"):
                    s.link_base = f"http://{self.headers.get('Host', 'localhost')}"  # links point at this server
                    q = json.loads(body)
                    self._json(s.share_preview(q) if self.path.endswith("preview") else s.share(q))
                elif self.path == "/api/share/stop":
                    self._json(s.share_stop(json.loads(body)["share_id"]))
                elif self.path == "/api/plan":
                    q = json.loads(body)
                    self._json(s.plan(q["origin"], q["destination"], q.get("mode", "arrive"), q.get("time")))
                elif self.path == "/api/schedule":
                    self._json({"ok": s.schedule_upload(self.headers.get("X-Filename", "schedule.txt"), body)})
                elif self.path == "/api/schedule/confirm":
                    self._json(s.schedule_confirm(json.loads(body)["classes"]))
                elif self.path == "/api/schedule/cancel":
                    self._json(s.schedule_cancel())
                elif self.path == "/api/schedule/review":
                    self._json(s.schedule_review())
                elif self.path == "/api/upload":
                    self._json({"ok": s.upload(self.headers.get("X-Filename", "upload.txt"), body)})
                elif self.path == "/api/save":
                    self._json({"ok": True, "path": str(s.save().relative_to(ROOT))})
                else:
                    self._json({"error": "not found"}, 404)
            except Exception as e:
                self._json({"error": f"{type(e).__name__}: {e}"}, 400)

    return Handler


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8239)
    opts = ap.parse_args()
    print("loading transit feeds...")
    app = App(Router(gtfs.load()), gtfs.load_shapes())
    server = ThreadingHTTPServer(("127.0.0.1", opts.port), handler(app))
    server.daemon_threads = True
    print(f"bus-agent web app: http://localhost:{opts.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
