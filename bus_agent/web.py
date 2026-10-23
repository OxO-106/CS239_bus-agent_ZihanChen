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
from bus_agent.routing import Router, _short, clean_name, hhmm, parse_hhmm, walk_min
from bus_agent.tools import DAY_CODES
from bus_agent.trace import Trace
from bus_agent.world import World

ROOT = Path(__file__).resolve().parent.parent
PAGE = Path(__file__).resolve().parent / "static" / "index.html"
UPLOADS = ROOT / "data/local/uploads"
TRACES = ROOT / "data/local/traces"


# ---------- map geometry ----------

def route_geometry(router, route_id, origin=None, dest=None, shapes=None):
    """Polylines for a route_id: [{"kind": "walk" | "bus" | "rail", "line", "coords": [[lat, lon]]}].

    Rides follow the trip's GTFS shape when `shapes` has it, otherwise straight lines between stops."""
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
        self.map = {"shown": [], "others": [], "found": 0, "active": None, "origin": None, "dest": None}
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
        """Draw the routes of the latest plan that the Concierge's reply mentions (what the user is shown)."""
        if not self.world.plans:
            return
        plan = self.world.plans[-1]
        routes = plan["result"]["routes"]
        shown = [r for r in routes if all(mentions(reply, line) for line in r["lines"])]
        if not shown:
            return
        origin, dest = plan["points"]
        geo = [(r, route_geometry(self.router, r["route_id"], origin, dest, self.shapes)) for r in routes]
        drawn = [{**g, "labels": r["labels"], "next_departures": r["next_departures"], "walk_min": r["walk_min"],
                  "in_chat": r in shown}
                 for r, g in geo if g]
        # shown = what the assistant's reply mentions; others = the rest of plan_routes, for "Show all routes"
        self.map.update(origin=list(origin), dest=list(dest), found=len(routes),
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
                "contacts": {k: {"name": c["name"], "trusted": c.get("trusted", False)} for k, c in w.contacts.items()}}

    def _today(self):
        """Today's classes from the extracted schedule, with the next one's leave-by from the latest plan to it."""
        w = self.world
        if not w.schedule:
            return {"date": w.now.strftime("%a, %b %d"), "classes": None}
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
            if plan:  # earliest arrival among departures the rider can still make
                catchable = [(d["arrive"], hhmm(parse_hhmm(d["depart"]) - r["walk_min"]["to_stop"] * 60), r["lines"])
                             for r in plan["result"]["routes"] for d in r["next_departures"]
                             if parse_hhmm(d["depart"]) - r["walk_min"]["to_stop"] * 60 >= parse_hhmm(w.hhmm)]
                if catchable:
                    _, leave, lines = min(catchable)
                    nxt["leave_by"] = {"time": leave, "lines": lines}
        return {"date": w.now.strftime("%a, %b %d"), "classes": out}

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
