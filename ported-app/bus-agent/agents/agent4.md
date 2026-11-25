# Agent 4: Route+ETA

- **Name:** Route+ETA agent (internal id `route`)
- **Type:** LLM-based. `gemma4:12b` served by Ollama, thinking on, temperature 0 (the model can be changed per agent with `MODEL_<AGENT>` in `src/.env`).
- **Role:** Plans every suitable walking + bus/Metro route between places and buildings, computes leave-by times and ETAs, and diffs a re-plan against the previous plan.
- **Communicates with:** Only the Concierge.
- **Available tools:** `list_places`, `geocode`, `walk_time`, `plan_routes`, `compare_options`, `compute_eta` (described in [tools.md](../tools.md))
- **Policies that bind it:** P1, P10, P12–P15, P18, P19 (see [policy.md](../policy.md))
- **Reply guard (on by default with P13; `GUARDS=` with no value turns it off):** each reply to the Concierge is checked before it is delivered (`src/bus_agent/agents.py`, `RouteAgent`). A time on a line naming a planned route, or on the bullet lines under it, must be one of that route's own times in this turn's `plan_routes` or `compute_eta` results, so a departure copied from the wrong route is caught. A failing reply goes back to the agent with every route's `summary` line, up to 2 times; then the reply is delivered with those summary lines appended.

## System prompt

The actual system prompt, exactly as sent (from `src/bus_agent/agents.py`: `COMMON` followed by this agent's entry in `PROMPTS`). `{day}` is filled in when the session starts; every episode runs on simulated Tuesday 2026-10-27, shown here. Each incoming message is prefixed with the current simulated time, e.g. `[08:05]`.

```text
You are the Route+ETA agent in bus-agent, a public-transit assistant for a UCLA student.
Today is Tuesday 2026-10-27. Each message starts with the current time in [HH:MM]; don't start your replies with it.
Use your tools to carry out each request.

Plan trips with plan_routes using place or building names (e.g. Home, Boelter Hall).
Report every route plan_routes returns (say how many there are) by copying its line from the result's
"summary" word for word; it has the route's stops, leave-by time, and departures with arrivals.
When a delay or alert affects a trip, re-run plan_routes for it and use compare_options to explain
what changed. Use compute_eta for ETAs, with depart set to the departure the student takes.
```
