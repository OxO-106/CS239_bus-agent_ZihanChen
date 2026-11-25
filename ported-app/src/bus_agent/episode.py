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

TRAJECTORY_INTRO = ("Each step starts with the simulated time and the acting agent. Messages between agents are quoted; "
                    "a tool call is shown with a one-line summary of its result; each agent's reasoning is folded "
                    "above the step it led to. The complete log, with every full tool result, is the JSON trace.")

NAMES = {"user": "User", "concierge": "Concierge", "schedule": "Schedule", "transit": "Transit", "route": "Route+ETA",
         "share": "Share", "system": "System", "world": "World"}
HUB_TOOLS = {"ask_user", "ask_schedule_agent", "ask_transit_agent", "ask_route_agent", "ask_share_agent"}


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
    lines += ["## Trajectory", "", TRAJECTORY_INTRO, ""] + trajectory(events)
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


def trajectory(events):
    """Numbered steps: messages, tool calls with their results summarized, world events and outbox entries."""
    out, n, i = [], 0, 0
    while i < len(events):
        e, d = events[i], events[i]["data"]
        who = NAMES.get(e["agent"], e["agent"])
        if e["kind"] == "thought":
            out += [f"<details><summary>{who}'s reasoning</summary>", "", _quote(d), "", "</details>", ""]
            i += 1
            continue
        if e["kind"] in ("tool_call", "tool_result") and d["name"] in HUB_TOOLS:
            i += 1  # the hub's messages below already show the request and the reply
            continue
        n += 1
        head = f"**{n}.** `{e['t']}` "
        if e["kind"] == "message":
            text = d["text"].split("\n\nRaw tool results:")[0].strip()
            out += [head + f"**{who} → {NAMES.get(d['to'], d['to'])}**", "", _quote(text)]
        elif e["kind"] == "tool_call":
            # a tool may send to the outbox before its own result is logged: show the result with the call
            j = i + 1
            while j < len(events) and events[j]["agent"] == "world":
                j += 1
            res = events[j] if j < len(events) and events[j]["kind"] == "tool_result" else None
            args = ", ".join(f"{k}: {v if isinstance(v, str) else json.dumps(v)}" for k, v in d["arguments"].items())
            line = head + f"**{who} → `{d['name']}`**({args})"
            if res:
                line += " → " + summarize(d["name"], res["data"]["result"])
                events = events[:j] + events[j + 1:]  # local copy: the result is shown, drop it from the steps
            out.append(line)
        elif e["kind"] == "outbox":
            body = {k: v for k, v in d.items() if k not in ("at", "kind", "to")}
            out.append(head + f"**Outbox: {d['kind'].replace('_', ' ')} to {d.get('to')}** {json.dumps(body, ensure_ascii=False)}")
        elif e["kind"] == "event":
            body = {k: v for k, v in d.items() if k not in ("at", "type", "notify")}
            out.append(head + f"**World: {d['type']}** {json.dumps(body, ensure_ascii=False)}")
        else:
            out.append(head + f"**{who}: {e['kind']}** {_short(d, 300)}")
        out.append("")
        i += 1
    return out


def summarize(tool, r):
    """One line for a tool result; the full result stays in the JSON trace."""
    if isinstance(r, dict) and r.get("error"):
        return f"error: {r['error']}"
    if tool == "plan_routes":
        def one(route):
            dep = (route.get("next_departures") or [{}])[0]
            late = "" if dep.get("on_time_for_class", True) else " (late)"
            return f"{'+'.join(route['lines'])} {dep.get('depart', '?')}→{dep.get('arrive', '?')}{late}"
        excluded = f"; {len(r.get('excluded', []))} excluded" if r.get("excluded") else ""
        return f"**{r['count']} routes** {r['origin']} → {r['destination']}: " + ", ".join(map(one, r["routes"])) + excluded
    if tool == "compute_eta":
        delay = f", delay {r['delay_min']} min" if r.get("delay_min") else ""
        return f"ETA **{r['eta']}** (departs {r['depart']}{delay})"
    if tool in ("get_schedule", "get_realtime_arrivals"):
        delay = f", delay {r['delay_min']} min" if r.get("delay_min") else ""
        near = f" (nearest stop to {r['near']})" if r.get("near") else ""
        return f"{r['line']} at {r['stop']}{near}: " + ", ".join(r["departures"]) + delay
    if tool == "get_service_alerts":
        return f"{len(r['alerts'])} alerts; delays: " + (", ".join(f"{x['line']} +{x['delay_min']} min" for x in r["delays"]) or "none")
    if tool.startswith("extract_schedule"):
        cls = [f"{c['course']} {'/'.join(c['days'])} {c['start']}–{c['end']} ({c['confidence']})" for c in r.get("classes", [])]
        return f"**{len(cls)} classes**: " + "; ".join(cls)
    if tool == "create_share":
        fields = ", ".join(k for k, v in r["fields"].items() if v) or "none"
        until = "until arrival" if r.get("stop_on_arrival") else f"until {r.get('expires_at')}"
        names = "" if r.get("place_names", True) else ", place names off"
        return f"share **{r['share_id']}** to {r['recipient']}: {fields}, {until}{names}"
    if tool == "update_share":
        sent = r.get("sent") or {}
        return f"update sent to {sent.get('to')}" + (f", ETA **{sent['eta']}**" if sent.get("eta") else "") + f" (share {r.get('share_status')})"
    if tool == "revoke_share":
        return f"share {r['share_id']} {r['status']}"
    if tool == "compare_options":
        kinds = {}
        for c in r.get("changes", []):
            kinds[c.get("status", "?")] = kinds.get(c.get("status", "?"), 0) + 1
        return ", ".join(f"{v} {k}" for k, v in kinds.items()) or "no changes"
    return _short(r, 200)


def _quote(text):
    return "\n".join("> " + line if line.strip() else ">" for line in str(text).strip().splitlines())


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
