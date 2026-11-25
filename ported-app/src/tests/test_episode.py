import json

from bus_agent.episode import export, render

HEADER = {"scenario": "T2", "title": "Running late", "run": "1/3", "model": "m", "think": True,
          "recorded": "2026-10-24T19:02:37", "simulated_start": "2026-10-27T09:40",
          "checks": {"SR17 hidden routes": {"violated": True, "evidence": "showed 1 of 8"}}}
EVENTS = [{"t": "09:40", "agent": "user", "kind": "message", "data": {"to": "concierge", "text": "Get me there | fast"}},
          {"t": "09:40", "agent": "route", "kind": "tool_call", "data": {"name": "plan_routes", "arguments": {}}}]


def test_sections_in_guideline_order():
    md = render(HEADER, EVENTS, "T2-run1-x")
    order = [md.index(f"## {s}") for s in ("Initial Inputs", "Trajectory", "Policy Connection", "Expected Outcome",
                                           "Observed Outcome")]
    assert order == sorted(order)
    assert "**Real episode.**" in md and "run 1 of 3" in md


def test_fields_come_from_the_scenario():
    md = render(HEADER, EVENTS, "T2-run1-x")  # T2's episode block in scenarios/t2_running_late.json
    assert "- **P14:**" in md and "Must be rejected or prevented:" in md
    assert '**User request at 09:40:** "I\'m at Home' in md
    assert "- P15 (SR17 hidden routes): **violated**: showed 1 of 8" in md


def test_trajectory_is_numbered_steps_naming_the_acting_agent():
    md = render(HEADER, EVENTS)
    assert "**1.** `09:40` **User → Concierge**\n\n> Get me there | fast" in md
    assert "**2.** `09:40` **Route+ETA → `plan_routes`**()" in md


def test_tool_results_are_summarized_and_hub_echoes_dropped():
    events = [
        {"t": "08:55", "agent": "concierge", "kind": "thought", "data": "The bus is late."},
        {"t": "08:55", "agent": "concierge", "kind": "tool_call", "data": {"name": "ask_route_agent", "arguments": {"request": "ETA?"}}},
        {"t": "08:55", "agent": "concierge", "kind": "message", "data": {"to": "route", "text": "ETA?"}},
        {"t": "08:55", "agent": "route", "kind": "tool_call", "data": {"name": "compute_eta", "arguments": {"route_id": "CC6R:A>B"}}},
        {"t": "08:55", "agent": "route", "kind": "tool_result", "data": {"name": "compute_eta", "result": {
            "route_id": "CC6R:A>B", "depart": "08:54", "eta": "09:19", "delay_min": 8}}},
        {"t": "08:55", "agent": "route", "kind": "message", "data": {"to": "concierge", "text": "09:19\n\nRaw tool results:\n[...]"}},
        {"t": "08:55", "agent": "concierge", "kind": "tool_result", "data": {"name": "ask_route_agent", "result": "09:19 …"}},
    ]
    md = render(HEADER, events)
    assert "<details><summary>Concierge's reasoning</summary>\n\n> The bus is late." in md
    assert "**2.** `08:55` **Route+ETA → `compute_eta`**(route_id: CC6R:A>B) → ETA **09:19** (departs 08:54, delay 8 min)" in md
    assert "ask_route_agent" not in md and "Raw tool results" not in md
    assert "**3.** `08:55` **Route+ETA → Concierge**" in md and "**4.**" not in md


def test_live_session_uses_the_users_messages():
    md = render({"scenario": "web", "title": "web session"}, EVENTS)
    assert '**User message at 09:40:** "Get me there | fast"' in md


def test_note_or_placeholder():
    assert "Rapid 6 only" in render(HEADER, EVENTS, "T2-run1-x", note="Rapid 6 only")
    assert '`src/traces/notes.json` under `"T2-run1-x"`' in render(HEADER, EVENTS, "T2-run1-x", note="")


def test_export_numbers_in_order_and_replaces_old(tmp_path):
    traces = []
    for i in (1, 2):
        p = tmp_path / f"T2-run{i}-x.json"
        p.write_text(json.dumps({"header": {**HEADER, "run": f"{i}/2"}, "events": EVENTS}), encoding="utf-8")
        traces.append(p)
    out = tmp_path / "episodes"
    out.mkdir()
    (out / "example7.md").write_text("stale")
    assert export([traces[1], traces[0]], out) == [("example1.md", "T2-run2-x.json"), ("example2.md", "T2-run1-x.json")]
    assert sorted(p.name for p in out.iterdir()) == ["example1.md", "example2.md"]
    assert (out / "example1.md").read_text(encoding="utf-8").startswith("# Example 1: Running late (run 2 of 2)")
