"""JSON + Markdown run traces: agent thoughts, tool calls, inter-agent messages, observations."""
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class Trace:
    def __init__(self, header):
        self.header = header
        self.events = []
        self.clock = lambda: ""

    def log(self, agent, kind, data):
        # copy now: tools return live world objects (e.g. a share) that change later
        data = json.loads(json.dumps(data, ensure_ascii=False, default=str))
        self.events.append({"t": self.clock(), "agent": agent, "kind": kind, "data": data})

    def save(self, out_dir=ROOT / "traces", stem=None):
        out_dir = Path(out_dir)
        out_dir.mkdir(exist_ok=True)
        stem = stem or f"{self.header.get('scenario', 'run')}-{datetime.now():%Y%m%d-%H%M%S}"
        (out_dir / f"{stem}.json").write_text(
            json.dumps({"header": self.header, "events": self.events}, indent=1, ensure_ascii=False), "utf-8")
        (out_dir / f"{stem}.md").write_text(self.markdown(), "utf-8")
        return out_dir / stem

    def markdown(self):
        h = self.header
        lines = [f"# Trace {h.get('scenario', '')}: {h.get('title', '')}", ""]
        lines += [f"- **{k}:** {v if not isinstance(v, (list, dict)) else json.dumps(v)}"
                  for k, v in h.items() if k not in ("scenario", "title")]
        lines += ["", "| Time | Agent | Kind | Detail |", "|---|---|---|---|"]
        for e in self.events:
            lines.append(f"| {e['t']} | {e['agent']} | {e['kind']} | {_cell(e)} |")
        return "\n".join(lines) + "\n"


def _cell(e):
    d = e["data"]
    if e["kind"] == "tool_call":
        text = f"`{d['name']}({json.dumps(d['arguments'], ensure_ascii=False)})`"
    elif e["kind"] == "tool_result":
        text = f"`{d['name']}` → {_short(d['result'])}"
    elif e["kind"] == "message":
        text = f"**→ {d['to']}:** {d['text']}"
    elif isinstance(d, str):
        text = d
    else:
        text = json.dumps(d, ensure_ascii=False)
    return text.replace("|", "\\|").replace("\n", "<br>")


def _short(value, limit=600):
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + f"… ({len(text)} chars)"
