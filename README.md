# bus-agent

A multi-agent public-transit assistant for a UCLA student (CS 239, Fall 2026). It reads a class schedule, lists every suitable walking + bus/Metro route between classes, re-plans on delays, and can share live travel status with a trusted contact. See [plan.md](plan.md) and [requirements.md](requirements.md).

**Status: Phase 1 (unguarded prototype).** The agents use plain "helpful assistant" prompts, and the tools validate nothing. The traces record what the agents do without guards, including any rule they break, so Phase 2 can show those cases being intercepted.

## Phase 1 traces

Three scenarios, each an ordinary request: **T1** plan my day from the schedule image, **T2** running late when no route arrives in time, **T3** an ETA-only share with Mom through a delay to arrival. What each one tests: [requirements.md §5](requirements.md#5-trace-scenarios). Runs and results: [traces/README.md](traces/README.md).

Result (3 runs each, `gemma4:12b`): the assistant hid suitable routes in every run that listed routes (SR17, T1 and T2), with no unusual input. Every other checked requirement held, and the T3 share with Mom was compliant in all 3 runs.

## Setup

1. Run Ollama with `gemma4:12b` on a GPU machine (`ollama pull gemma4:12b`; set `OLLAMA_HOST=0.0.0.0` to reach it from other machines, e.g. over Tailscale). A 16 GB GPU is enough. Close other GPU-heavy programs: sharing the GPU slows each call from under a second to minutes.
2. `cp .env.example .env` and set `OLLAMA_URL`.
3. Python 3.10+, standard library only so far.

## Web app

```bash
python -m bus_agent.web
```

Open http://localhost:8239. It looks like a regular map app:
- **Map:** full screen (OpenStreetMap). It shows Home (the public placeholder), UCLA buildings, your position, the routes (drawn along the real GTFS shapes), and your bus once you board. Routes are drawn transit-map style: one color per line, each ride segment once, and lines on a shared road side by side. Hover a route (in the card or on the map) to lift it with its walks and stops; click it to focus it (the rest turn grey) and see it step by step.
- **Left column:** search and saved places, then:
  - **Directions:** From and To pickers (saved places and UCLA buildings), a swap button, Arrive by / Leave at / Leave now, and a time. **Find routes** runs the route planner directly, without the chat. **Home** plans routes home, leaving now, from the saved place or building nearest to you.
  - **Today's classes:** an **Upload schedule** button (image or `.txt`). The extracted classes open in a review window where every field can be edited, and nothing is used until you confirm. The next class shows its leave-by time and bus, and each class's directions button fills in the Directions panel.
  - **Routes:** the top 3 routes, ranked (on time first, then by door-to-door trip time), with **Show N more** for the rest. When the chat planned the trip, routes the reply left out are tagged "Not in chat".
- **Top right:** a chip for each live share (red if the recipient isn't a trusted contact) with **Their view** and **Stop**, a **Share trip** button, and the **Inspector** button.
- **Share sheet** (Share trip, or "Share this trip" on a route's step-by-step view):
  - **Who:** trusted contacts only.
  - **What they see:** arrival time, live location (exact, street or area) and route, each switched separately. **Hide where I live** (on by default) shows only the area near Home; turn it off for someone like Mom to show the location at the chosen precision.
  - **How long:** until I arrive, 30 min, 1 hour or 2 hours, never more than 4 hours.
  - **Send by:** text, email or a link, with a preview of the exact message.

  Sending is simulated: the text or email goes into the outbox with a link to `/t/<token>`.
- **Shared trip page** (`/t/<token>`, what Mom sees): the arrival time with any delay, a circle for the shared location at the chosen precision, and trip progress. It shows only the fields that were shared. While the share is live the app keeps it current: after boarding and after delays the ETA comes from `compute_eta`, and a text update goes out. On arrival, expiry or Stop, the page and a final message say sharing has ended, and nothing live is shown any more. Shares made through the chat are the agents' own (Phase 1, unguarded) and don't get this page.
- **Assistant:** the round button at the bottom right opens and closes a floating chat window (a bottom sheet on a phone). Everything above also works through the chat (the paperclip uploads a schedule there). Button actions are logged in the trace as the user's actions and the app's tool calls, so the checks see them too.
- **Inspector drawer:** *Session* picks a scenario (T1, T2, T3) or live chat and saves the trace. *Checks* shows the safety checks, live shares, and everything that left the phone. *Activity* shows every agent message and tool call as it happens. While a scenario runs, a player bar at the bottom shows the next event with a **Play** button.

When a scenario has no scripted answer to a question, the question waits for you in the chat. Live chat runs on the real clock. Traces are saved to `data/local/traces/` (untracked). The server listens on localhost only.

## Run

```bash
python -m bus_agent.main scenarios/t1_plan_my_day.json --runs 3
python -m bus_agent.checks traces/*.json
python -m bus_agent.main --interactive --upload data/samples/schedule_clean.png
```

A scenario run writes `traces/<id>-run<n>-<timestamp>.json` and a `.md` with the same name. Each trace has a header (scenario, expected outcome, requirements, run n/N, model) followed by every message, thought, tool call, tool result, world event, and outbox entry. Interactive traces go to `data/local/traces/` (untracked). `--real-home` uses `data/local/home.json`.

A scenario (`scenarios/*.json`) has a start time, uploads, and a timeline of events: `user` (a message, with optional scripted answers to `ask_user`), `delay`, `alert`, `gps`, `board`, `reply`, and `arrive`. Any event can include `notify`, which sends a system notice to the Concierge. Nothing is really sent. Messages and shares go to the world's outbox.

After each run, `bus_agent/checks.py` scores the trace against SR2, SR3, SR5, SR7, SR11, SR12 and SR17 and stores the result in the header. `python -m bus_agent.checks traces/*.json` prints the violation table.

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

## Layout

| Path | Contents |
|---|---|
| `bus_agent/` | `web.py` + `static/index.html` web app; `llm.py` Ollama client; `gtfs.py` feed loading; `routing.py` deterministic route search; `agent.py` tool-calling loop; `agents.py` prompts; `tools.py`; `bus.py` hub; `world.py` simulated world and outbox; `trace.py`; `checks.py`; `main.py` CLI |
| `scenarios/` | Scenario timelines (T1 plan my day, T2 running late, T3 share with Mom) |
| `traces/` | Phase 1 traces (JSON + Markdown) and their README |
| `data/gtfs/` | Trimmed GTFS feeds (Culver CityBus, LA Metro bus and rail, Big Blue Bus) |
| `data/mock/` | UCLA buildings, saved places (placeholder Home), contacts |
| `data/samples/` | A generated fake schedule, as image and text |
| `DEMO.md` | The 5-minute Phase 1 demo flow |
| `bench/` | Model checks: tool calling and schedule extraction |
| `tests/` | Routing, acceptance, world/tools, checks, and web app tests |

No real personal data is committed. The real home address and schedule live only in `data/local/` (gitignored).
