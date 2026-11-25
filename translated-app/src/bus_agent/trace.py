"""JSON, JSONL + Markdown run traces: agent thoughts, tool calls, inter-agent messages, observations.

The Markdown is an episode in the submission format (bus_agent/episode.py). The JSONL is the
Phase 2 trajectory: line 1 is the header, then one event per line in the order they happened.
"""
import json
from datetime import datetime
from pathlib import Path

from bus_agent.episode import render

ROOT = Path(__file__).resolve().parent.parent


class Trace:
    def __init__(self, header):
        self.header = header
        self.events = []
        self.clock = lambda: ""
        self.listeners = []  # called with each new event (the web app streams them)

    def log(self, agent, kind, data):
        # copy now: tools return live world objects (e.g. a share) that change later
        data = json.loads(json.dumps(data, ensure_ascii=False, default=str))
        event = {"t": self.clock(), "agent": agent, "kind": kind, "data": data}
        self.events.append(event)
        for fn in self.listeners:
            fn(event)

    def save(self, out_dir=ROOT / "traces", stem=None):
        out_dir = Path(out_dir)
        out_dir.mkdir(exist_ok=True)
        stem = stem or f"{self.header.get('scenario', 'run')}-{datetime.now():%Y%m%d-%H%M%S}"
        (out_dir / f"{stem}.json").write_text(
            json.dumps({"header": self.header, "events": self.events}, indent=1, ensure_ascii=False), "utf-8")
        (out_dir / f"{stem}.md").write_text(self.markdown(stem), "utf-8")
        write_jsonl(self.header, self.events, out_dir / f"{stem}.jsonl")
        return out_dir / stem

    def markdown(self, stem=None):
        return render(self.header, self.events, stem)


def write_jsonl(header, events, path):
    """Header line ({"type": "header", ...}), then each event with its sequence number."""
    lines = [{"type": "header", **header}]
    lines += [{"seq": i, "type": "event", **e} for i, e in enumerate(events)]
    Path(path).write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in lines), "utf-8")


if __name__ == "__main__":  # python -m bus_agent.trace traces/T1-....json [...]: convert old traces
    import sys
    for arg in sys.argv[1:]:
        src = Path(arg)
        d = json.loads(src.read_text("utf-8"))
        write_jsonl(d["header"], d["events"], src.with_suffix(".jsonl"))
        print(src.with_suffix(".jsonl"))
