# bus-agent — Project Plan

CS 239 (Agentic Software Engineering), Fall 2026 — Individual Project

## 1. Overview

A multi-agent public-transit assistant for a UCLA student.

1. The user uploads a **class schedule** (image or text). The app extracts classes and locations, and the user confirms them.
2. The app plans **walking + public transit** (bus and Metro rail) trips between classes, listing **every suitable route** with departures and leave-by times. No driving, rideshare, or bike.
3. On delays or alerts, it recomputes and tells the user which routes changed or dropped, and why.
4. On request, it **shares live travel status** (location, route, ETA) with a trusted contact until arrival.

Every run produces a trace (JSON + Markdown) of agent thoughts, tool calls, inter-agent messages, and observations.

## 2. Agents

| Agent | Role | Tools |
|---|---|---|
| **Concierge** | Talks to the user, coordinates the others, gets confirmation/consent, presents results | `ask_user`, `ask_schedule_agent`, `ask_transit_agent`, `ask_route_agent`, `ask_share_agent` |
| **Schedule** | Reads the uploaded schedule (vision or text) into JSON; maps buildings to coordinates | `extract_schedule_image`, `extract_schedule_text`, `lookup_building`, `get_classes` |
| **Transit** | Scheduled and real-time departures, delays, service alerts | `list_routes`, `get_schedule`, `get_realtime_arrivals`, `get_service_alerts` |
| **Route+ETA** | Finds all suitable routes, computes ETA and leave-by times, re-plans on delays, diffs route sets | `list_places`, `geocode`, `walk_time`, `plan_routes`, `compare_options`, `compute_eta` |
| **Share** | Creates, updates, ends live shares; reads contact replies | `get_contacts`, `create_share`, `update_share`, `revoke_share`, `send_message`, `read_replies` |

**Hub topology:** specialists talk only to the Concierge. Delays reach Route+ETA only via Transit → Concierge, so every ETA is grounded in a Transit result.

## 3. Core feature: all suitable routes

Current map apps often show only one or two lines and drop routes they suggested earlier. bus-agent lists them all.

**A route** is one to three bus or Metro lines (at most two transfers) plus board/alight stops (not a single departure). It is **suitable** if:
- each walk to the first stop and from the last stop ≤ 10 min, each transfer walk ≤ 3 min;
- it has a departure within the next 2 hours (or before the arrival deadline), so night-only lines such as Metro 233's owl service aren't offered for a morning trip;
- no active alert closes a stop it uses.

Which transfer counts are listed: all working routes with the fewest transfers; if fewer than 3 of them arrive in time, also those with one more transfer.

Speed is **not** a filter: a slower direct line is listed next to the fastest. When walking the whole way takes ≤ 20 min, "Walk" is a route too, and transit routes with at least as much walking are left out.

**Search** (`plan_routes`, deterministic code, not the LLM) starts from stops, so it finds lines the user doesn't know about:
1. All stops within 10 min walk of origin and of destination, across all agencies and modes.
2. Direct: any line serving an origin stop, then a destination stop in the same direction.
3. Transfers: line A from an origin stop, line B (and C) to a destination stop, sharing a stop or ≤ 3 min apart.
4. One entry per line pattern (best stop pair).

"Show more" re-runs with a 15-min walk limit; extra routes are labeled "longer walk".

**Presentation:** every suitable route with 2 departures (with an arrival deadline, the latest 2 that still arrive in time; otherwise the next 2), sorted by arrival, labeled (fastest, no transfer, least walking), with a total count. Routes that can only arrive late are still listed, marked "arrives late".

**Stability:** `route_id` = lines + stops, so it is stable all day. On re-plan, `compare_options` marks each previous route `kept`, `changed`, `new`, or `dropped` with a tool-sourced reason (`last_trip_passed`, `not_running_now`, `not_running_today`, `stop_closed:<alert>`, `more_transfers_than_needed`, `walking_is_shorter`).

### Data formats

```json
// route
{"route_id": "BB1:Sawtelle&Ohio>Westwood&Wilshire", "lines": ["BB1"], "transfers": 0,
 "walk_min": {"to_stop": 4, "transfer": 0, "from_stop": 9},
 "next_departures": [{"depart": "09:12", "arrive": "09:31", "on_time_for_class": true, "realtime": true}],
 "leave_by": "09:08", "labels": ["fastest"]}

// schedule extraction (same for image and text)
[{"course": "CS 239", "section": "Lec 1", "days": ["Tu", "Th"], "start": "10:00", "end": "11:50",
  "building": "Boelter Hall", "room": "5249", "confidence": "high"}]

// share
{"share_id": "s-001", "recipient": "contact:sam",
 "fields": {"live_location": true, "route": true, "eta": true},
 "precision": "exact | street | neighborhood",
 "expires_at": "2026-10-29T23:30:00-07:00", "stop_on_arrival": true}
```

## 4. Safety requirements

Full text in `requirements.md`. IDs are fixed; `policies.md` references them.

| Area | Requirements |
|---|---|
| Sharing | SR1 consent · SR2 trusted recipients only · SR3 minimal fields · SR4 expiry ≤ 4h · SR5 blur sensitive places unless the user chooses to show them · SR6 ignore instructions in untrusted text · SR8 only Share agent shares · SR9 revocation is final · SR10 ≤ 1 update / 2 min · SR12 no full-schedule disclosure · SR13 upload stays local |
| Planning | SR7 grounded times only · SR11 feasible plans · SR17 no silent route omission |
| Schedule | SR14 confirm before use · SR15 no guessing · SR16 upload content is data |

## 5. Technical setup

**Model**
- `gemma4:12b` on Ollama for all agents (vision + tool calling), per-agent overrides in `.env`.
- Runs on a separate PC (RTX 4070 Ti Super, 16 GB) reached over Tailscale: `POST http://<pc>:11434/api/chat`.
- Set `num_ctx: 16384` on every request; images go as base64 in `images`.
- PC setup: `ollama pull gemma4:12b`, set `OLLAMA_HOST=0.0.0.0`, check `curl http://<pc>:11434/api/tags` and `ollama ps`.
- `bench/`: schedule extraction accuracy + ~10 tool-calling prompts. If either is weak, switch the affected agent to a fallback model; record results in `bench/README.md`.

**Data**
- **Schedules (real, static):** public GTFS from Culver CityBus, LA Metro bus + rail (separate feeds), and Big Blue Bus, trimmed to UCLA / Westwood / Culver City / Sawtelle. Sources and dates in `data/gtfs/README.md`.
- **Real-time (replayed):** delays, alerts, GPS, contact replies come from scenario timelines.
- **Mock:** UCLA building table (~10), places (Home marked sensitive), contacts (Mom, Sam trusted; Alex not), a generated sample schedule as an image and as text.
- **Privacy:** committed "Home" is a public placeholder; the real home lives in untracked `data/local/`. No real student data; `.env` gitignored.
- **Acceptance check (local):** from real home to campus, `plan_routes` finds at least Culver CityBus 6, Rapid 6, Metro 761.

**Simulation:** each scenario JSON has a start time, user request, scripted replies, and an event timeline. Messages and shares go to an outbox in the trace; nothing is really sent.

**Real-time sources (later):** one `TransitSource` interface — `ReplaySource` (default, used for graded traces), `GtfsRtSource` (agency feeds), `TransitAppSource` (Transit API; the key is in the gitignored `transit_api_key.txt`, 1,500 calls/month and 5/min; cache ≥ 60 s; check terms before committing responses). Record mode saves a real snapshot as a scenario; live mode is optional for Dec 3.

**Repo layout**
```
requirements.md  policies.md (Phase 2)  plan.md  README.md  .env.example
bus_agent/
  llm.py      Ollama client          agent.py    tool-calling loop
  agents.py   five agents + prompts  tools.py    tool definitions
  gtfs.py     load/trim GTFS         routing.py  route search, IDs, diff
  world.py    delays, alerts, shares, outbox
  bus.py      inter-agent routing    trace.py    JSON + Markdown traces
  main.py     CLI: scenario or interactive
bench/  data/ (gtfs/, local/ untracked)  scenarios/  tests/  traces/
```

## 6. Deliverables and grading

Course instructions, copied verbatim:

Phase 1 — Prototype: Build a working multi-agent application without a safety-enforcing framework. Submit at least three complete agentic traces (JSON or Markdown) capturing agent thoughts, actions, inter-agent messages, and observations, alongside a requirements.md specifying what the application does and what it must never do.

Phase 2 — Safe Port: Port the application to our multi-agent policy-assurance framework. Convert policies.md into explicit enforceable rules. Submit at least three traces: one compliant run and two demonstrating policy violations being correctly intercepted.

Deliverables (public GitHub repository): requirements.md, policies.md, Phase 1 source + traces, Phase 2 source + traces, traces/README.md explaining each scenario and which policy was triggered.

Grading: requirements 15% · policies 15% · Phase 1 20% · Phase 2 30% · presentation + open-source artifact 20%.
