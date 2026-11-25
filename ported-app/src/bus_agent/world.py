"""Simulated world state: clock, uploads, delays, alerts, GPS, shares, outbox, contact replies.

Everything that would touch the outside world is recorded here instead (nothing is really sent).
Scenario events (format in README.md) change this state as the clock advances.
"""
import json
import os
from datetime import datetime
from pathlib import Path

from bus_agent.routing import clean_name

ROOT = Path(__file__).resolve().parent.parent


def _json(path):
    return json.loads(Path(path).read_text())


class World:
    def __init__(self, router, start, trace, uploads=None, real_home=False):
        self.router = router
        self.now = datetime.fromisoformat(start)
        self.trace = trace
        self.buildings = _json(ROOT / "data/mock/buildings.json")
        self.places = _json(ROOT / "data/mock/places.json")
        self.contacts = _json(ROOT / "data/mock/contacts.json")
        local_home = ROOT / "data/local/home.json"
        if real_home and local_home.exists():  # local runs only; graded traces use the placeholder
            self.places["Home"].update({k: v for k, v in _json(local_home).items() if k in ("lat", "lon")})
        self.uploads = uploads or {}       # upload_id -> {"image": path} | {"text": str}
        self.schedule = None               # last extraction result
        self.line_delays = {}              # line -> minutes late
        self.alerts = []                   # [{"id", "text", "lines", "closed_stops": [stop names]}]
        self.gps = dict(self.places["Home"])
        self.active_trip = None            # {"route_id", "depart"} once the rider boards
        self.chosen_trip = None            # {"route_id", "depart"} the rider said they'll take (P13 guard)
        # policies the tools and the Concierge enforce (GUARDS=P4,P5,P13,P15 by default; GUARDS= with no value: none)
        self.guards = {g.strip().upper() for g in os.environ.get("GUARDS", "P4,P5,P13,P15").split(",") if g.strip()}
        self.plans = []                    # plan_routes results, newest last
        self.shares = {}
        self.outbox = []
        self.replies = []                  # unread contact replies
        self.user_replies = []             # scripted answers to ask_user

    @property
    def hhmm(self):
        return self.now.strftime("%H:%M")

    def set_time(self, hhmm):
        h, m = map(int, hhmm.split(":"))
        self.now = self.now.replace(hour=h, minute=m)

    def apply(self, event):
        """Apply one scenario event (except "user", which the runner sends to the Concierge)."""
        kind = event["type"]
        if kind == "delay":
            self.line_delays[event["line"]] = event["minutes"]
        elif kind == "alert":
            self.alerts.append({k: event.get(k) for k in ("id", "text", "lines", "closed_stops")})
        elif kind == "gps":
            self.gps = {"lat": event["lat"], "lon": event["lon"]}
        elif kind == "board":
            self.active_trip = {"route_id": event["route_id"], "depart": event["depart"]}
        elif kind == "reply":
            self.replies.append({"from": event["from"], "text": event["text"], "at": self.hhmm})
        elif kind == "arrive":
            place = self.buildings.get(event["place"]) or self.places[event["place"]]
            self.gps = {"lat": place["lat"], "lon": place["lon"]}
            self.active_trip = self.chosen_trip = None
            for share in self.shares.values():
                if share["status"] == "active" and share["stop_on_arrival"]:
                    share["status"] = "ended"
                    self.trace.log("world", "observation", {"share_ended_on_arrival": share["share_id"]})
        self.trace.log("world", "event", event)

    def trip_delays(self):
        """{trip_id: seconds late} for the router, from per-line delays."""
        return {t.id: minutes * 60 for line, minutes in self.line_delays.items()
                for t in self.router.by_line.get(line, ())}

    def closed_stops(self):
        """{stop_id: alert_id} for stops closed by active alerts, matched by cleaned stop name."""
        closed = {}
        for alert in self.alerts:
            names = {clean_name(n).lower() for n in alert.get("closed_stops") or ()}
            for stop in self.router.net.stops.values():
                if clean_name(stop.name).lower() in names:
                    closed[stop.id] = alert["id"]
        return closed

    def send(self, kind, payload):
        entry = {"at": self.hhmm, "kind": kind, **payload}
        self.outbox.append(entry)
        self.trace.log("world", "outbox", entry)
        return entry
