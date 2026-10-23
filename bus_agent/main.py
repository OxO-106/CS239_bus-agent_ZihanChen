"""CLI entry point: run a scenario or interactive mode.

python -m bus_agent.main scenarios/t1_clean_trip.json [--runs N]
python -m bus_agent.main --interactive [--upload path] [--real-home]
"""
import argparse
import json
import os
from datetime import datetime
from pathlib import Path

from bus_agent import gtfs
from bus_agent.agents import build
from bus_agent.bus import Bus
from bus_agent.routing import Router
from bus_agent.trace import Trace
from bus_agent.world import World

ROOT = Path(__file__).resolve().parent.parent


def _uploads(spec):
    out = {}
    for uid, u in (spec or {}).items():
        out[uid] = {"image": u["image"]} if "image" in u else {"text": (ROOT / u["text"]).read_text()}
    return out


def run_scenario(path, router, run=1, runs=1):
    sc = json.loads(Path(path).read_text())
    trace = Trace({"scenario": sc["id"], "title": sc["title"], "expected": sc["expected"],
                   "requirements": sc.get("requirements", []), "run": f"{run}/{runs}",
                   "model": os.environ.get("MODEL", "gemma4:12b"), "simulated_start": sc["start"],
                   "uploads": sc.get("uploads", {}), "recorded": datetime.now().isoformat(timespec="seconds")})
    world = World(router, sc["start"], trace, _uploads(sc.get("uploads")))
    trace.clock = lambda: world.hhmm
    bus = Bus(trace, lambda: world.hhmm)

    def ask_user(question):
        trace.log("concierge", "message", {"to": "user", "text": question})
        answer = world.user_replies.pop(0) if world.user_replies else "(no reply)"
        trace.log("user", "message", {"to": "concierge", "text": answer})
        return {"answer": answer}

    concierge = build(world, bus, trace, ask_user)
    for event in sc["events"]:
        world.set_time(event["at"])
        if event["type"] == "user":
            world.user_replies = list(event.get("replies", []))  # answers to ask_user during this event only
            trace.log("user", "message", {"to": "concierge", "text": event["text"]})
            reply = concierge.run(f"[{world.hhmm}] {event['text']}")
            trace.log("concierge", "message", {"to": "user", "text": reply})
            world.user_replies = []
        else:
            world.apply(event)
            if event.get("notify"):
                trace.log("system", "message", {"to": "concierge", "text": event["notify"]})
                reply = concierge.run(f"[{world.hhmm}] (system notice) {event['notify']}")
                trace.log("concierge", "message", {"to": "user", "text": reply})
    trace.header["final_shares"] = list(world.shares.values())
    trace.header["outbox_count"] = len(world.outbox)
    stem = f"{sc['id']}-run{run}-{datetime.now():%Y%m%d-%H%M%S}"
    return trace.save(stem=stem)


def interactive(router, upload=None, real_home=False):
    trace = Trace({"scenario": "interactive", "title": "interactive session",
                   "recorded": datetime.now().isoformat(timespec="seconds")})
    uploads = {}
    if upload:
        p = Path(upload)
        uploads["u1"] = {"image": str(p.resolve())} if p.suffix.lower() in (".png", ".jpg", ".jpeg") else {"text": p.read_text()}
    world = World(router, datetime.now().isoformat(timespec="minutes"), trace, uploads, real_home=real_home)
    trace.clock = lambda: world.hhmm
    bus = Bus(trace, lambda: world.hhmm)

    def ask_user(question):
        print(f"\nassistant> {question}")
        answer = input("you> ")
        trace.log("user", "message", {"to": "concierge", "text": answer})
        return {"answer": answer}

    concierge = build(world, bus, trace, ask_user)
    if uploads:
        print("(schedule uploaded as u1)")
    while True:
        try:
            text = input("\nyou> ").strip()
        except EOFError:
            break
        if text in ("", "quit", "exit"):
            break
        world.now = datetime.now()
        trace.log("user", "message", {"to": "concierge", "text": text})
        reply = concierge.run(f"[{world.hhmm}] {text}")
        trace.log("concierge", "message", {"to": "user", "text": reply})
        print(f"\nassistant> {reply}")
    print("trace:", trace.save(ROOT / "data/local/traces"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scenario", nargs="?")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--interactive", action="store_true")
    ap.add_argument("--upload")
    ap.add_argument("--real-home", action="store_true", help="use data/local/home.json (interactive only)")
    opts = ap.parse_args()
    router = Router(gtfs.load())
    if opts.interactive:
        interactive(router, opts.upload, opts.real_home)
    else:
        for run in range(1, opts.runs + 1):
            print("trace:", run_scenario(opts.scenario, router, run, opts.runs))


if __name__ == "__main__":
    main()
