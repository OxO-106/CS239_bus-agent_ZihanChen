"""Episode Markdown in the submission format, and the export to bus-agent/episodes/.

Every trace is written as an episode: Initial Inputs, Trajectory, Policy Connection, Expected Outcome (the
guideline's sections, in its order), then Observed Outcome. The episode fields come from the scenario's
"episode" block; the observed outcome is the automatic checks plus an optional note per run from
traces/notes.json ({"<trace stem>": "note"}).

python -m bus_agent.episode traces/T1-run1-….json traces/T2-run1-….json …
    -> ../bus-agent/episodes/example1.md, example2.md, … in the order given (old example*.md are removed)
"""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EPISODES_DIR = ROOT.parent / "bus-agent" / "episodes"
NOTES = ROOT / "traces" / "notes.json"

# each automatic check (named by its safety requirement) and the policy it scores
CHECK_POLICY = {"SR2": "P3", "SR3": "P5", "SR5": "P7", "SR7": "P13", "SR11": "P14", "SR12": "P8", "SR17": "P15"}

TRAJECTORY_INTRO = ("Every step of the run in order. *Agent* is the acting agent (`user` is the user, `world` and "
                    "`system` the simulated environment). Kinds: `message` (to another agent or the user), `thought` "
                    "(the agent's reasoning), `tool_call`, `tool_result`, `outbox` (anything sent outside the app) and "
                    "world events. Long tool results are cut, with their full length in brackets.")


def scenario_for(header):
    """The scenario a trace was recorded from, or None (live chat, or a scenario that no longer exists)."""
    for p in (ROOT / "scenarios").glob("*.json"):
        sc = json.loads(p.read_text(encoding="utf-8"))
        if sc.get("id") == header.get("scenario"):
            return {**sc, "file": p.name}
    return None


def load_notes():
    return json.loads(NOTES.read_text(encoding="utf-8")) if NOTES.exists() else {}


def render(header, events, stem=None, title=None, note=None):
    sc = scenario_for(header)
    ep = header.get("episode") or (sc or {}).get("episode") or {}
    if note is None and stem:
        note = load_notes().get(stem)
    lines = [title or f"# Episode {header.get('scenario', '')}: {header.get('title', '')}", "", _label(header, sc, stem), ""]
    lines += ["## Initial Inputs", ""] + _inputs(header, events, sc, ep) + [""]
    lines += ["## Trajectory", "", TRAJECTORY_INTRO, "", "| Time | Agent | Kind | Detail |", "|---|---|---|---|"]
    lines += [f"| {e['t']} | {e['agent']} | {e['kind']} | {cell(e)} |" for e in events]
    lines += ["", "## Policy Connection", ""]
    lines += [f"- **{p['id']}:** {p['note']}" for p in ep.get("policies", [])] or ["- None recorded for this run."]
    lines += ["", "## Expected Outcome", ""]
    lines += [f"- {x}" for x in ep.get("expected", [])] or [f"- {header.get('expected', 'Not specified.')}"]
    if ep.get("prevented"):
        lines += ["", "Must be rejected or prevented:", ""] + [f"- {x}" for x in ep["prevented"]]
    lines += ["", "## Observed Outcome", "",
              note or f"_No note for this run yet: add one to `src/traces/notes.json` under `\"{stem}\"`._"]
    if header.get("checks"):
        lines += ["", "Automatic checks (`src/bus_agent/checks.py`):", ""]
        for name, r in header["checks"].items():
            verdict = "**violated**" if r["violated"] else "held"
            lines.append(f"- {CHECK_POLICY.get(name.split()[0], '?')} ({name}): {verdict}"
                         + (f": {r['evidence']}" if r.get("evidence") else ""))
    return "\n".join(lines) + "\n"


def _label(header, sc, stem):
    where = f"scenario `src/scenarios/{sc['file']}`" if sc else "a live session"
    run = f"run {header['run'].replace('/', ' of ')} of " if header.get("run") else ""
    model = f", model `{header['model']}`" + (", thinking on" if header.get("think") else "") if header.get("model") else ""
    raw = f" Raw trace: `src/traces/{stem}.json`." if stem else ""
    return f"**Real episode.** A recorded {run}{where}{model}, recorded {header.get('recorded', '?')}.{raw}"


def _inputs(header, events, sc, ep):
    out = [f"- **Receiving agent:** {ep.get('receiving_agents', 'Concierge')} (the only agent that talks to the user)."]
    resources = ep.get("resources", "")
    if header.get("simulated_start"):
        resources = f"Simulated start {header['simulated_start'].replace('T', ' ')}. " + resources
    if resources:
        out.append(f"- **Resources:** {resources.strip()}")
    if sc:
        for ev in sc["events"]:
            if ev["type"] == "user":
                out.append(f"- **User request at {ev['at']}:** \"{ev['text']}\"")
                out += [f"  - Scripted answer if the Concierge asks (`ask_user`): \"{r}\"" for r in ev.get("replies", [])]
            else:
                detail = json.dumps({k: v for k, v in ev.items() if k not in ("at", "type", "notify")}, ensure_ascii=False)
                notice = f" The Concierge is notified: \"{ev['notify']}\"" if ev.get("notify") else ""
                out.append(f"- **World event at {ev['at']}:** `{ev['type']}` {detail}.{notice}")
    else:  # live session: the user's own messages are the inputs
        out += [f"- **User message at {e['t']}:** \"{e['data']['text']}\"" for e in events
                if e["agent"] == "user" and e["kind"] == "message"]
    return out


def cell(e):
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


def export(traces, out_dir=EPISODES_DIR):
    """Write the given traces as example1.md, example2.md, … (in order), replacing the old ones."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("example*.md"):
        old.unlink()
    notes = load_notes()
    written = []
    for n, path in enumerate(traces, 1):
        path = Path(path)
        d = json.loads(path.read_text(encoding="utf-8"))
        h = d["header"]
        run = f" (run {h['run'].replace('/', ' of ')})" if h.get("run") else ""
        title = f"# Example {n}: {h.get('title', h.get('scenario', ''))}{run}"
        out = out_dir / f"example{n}.md"
        out.write_text(render(h, d["events"], path.stem, title, notes.get(path.stem)), encoding="utf-8")
        written.append((out.name, path.name))
    return written


def main():
    ap = argparse.ArgumentParser(description="Export traces as bus-agent/episodes/example<N>.md")
    ap.add_argument("traces", nargs="+", help="trace .json files, in episode order")
    ap.add_argument("--out", default=EPISODES_DIR, help="episodes folder (default: ../bus-agent/episodes)")
    opts = ap.parse_args()
    for name, src in export(opts.traces, opts.out):
        print(f"{name} <- {src}")


if __name__ == "__main__":
    main()
