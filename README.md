# bus-agent

A multi-agent public-transit assistant for a UCLA student (CS 239, Fall 2026). It reads a class schedule, lists every suitable walking + bus/Metro route between classes, re-plans on delays, and can share live travel status with a trusted contact. See [plan.md](plan.md) and [requirements.md](requirements.md).

## Setup

1. Run Ollama with `gemma4:12b` on a GPU machine (`ollama pull gemma4:12b`, `OLLAMA_HOST=0.0.0.0`).
2. `cp .env.example .env` and set `OLLAMA_URL`.
3. Python 3.10+, standard library only so far.

## Run

```bash
python -m bus_agent.main scenarios/t1_clean_trip.json --runs 3
python -m bus_agent.main --interactive --upload data/samples/schedule_clean.png
```

A scenario run writes `traces/<id>-run<n>-<timestamp>.json` and a `.md` with the same name. Each trace has a header (scenario, expected outcome, requirements, run n/N, model) followed by every message, thought, tool call, tool result, world event, and outbox entry. Interactive traces go to `data/local/traces/` (untracked). `--real-home` uses `data/local/home.json`.

A scenario (`scenarios/*.json`) has a start time, uploads, and a timeline of events: `user` (a message, with optional scripted answers to `ask_user`), `delay`, `alert`, `gps`, `board`, `reply`, and `arrive`. Any event can include `notify`, which sends a system notice to the Concierge. Nothing is really sent. Messages and shares go to the world's outbox.

Agents: the Concierge talks to the user and calls the specialists through `bus.py`, a hub that rejects specialist-to-specialist messages. Schedule, Transit, Route+ETA, and Share each have their own tools (`bus_agent/tools.py`). In Phase 1 the tools don't validate anything.

## Tests

```bash
python -m pytest
```

`tests/test_routing.py` checks the route rules on a synthetic network. `tests/test_acceptance.py` plans home → Boelter Hall on the real feeds and expects CC6, Rapid 6, and Metro 761. It reads `data/local/home.json` when that file exists, and otherwise starts from Expo/Sepulveda station. Feed sources: [data/gtfs/README.md](data/gtfs/README.md).

## Bench

```bash
python -m bench.tool_calls
python -m bench.extract_schedule
```

Results: [bench/README.md](bench/README.md).
