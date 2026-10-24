# Traces: Phase 1 (unguarded)

Each run writes `<scenario>-run<n>-<timestamp>.json` and a `.md` with the same name. The header records the scenario, expected outcome, requirements, run n/N, model, how specialists reply (`specialist_replies`), final shares, and the automatic checks (`bus_agent/checks.py`). The event list records every user message, agent thought, tool call, tool result, inter-agent message, world event, and outbox entry.

Model `gemma4:12b`, `think: false`, temperature 0. Simulated day: Tuesday 2026-10-27. The committed Home is the placeholder at Expo/Sepulveda station.

## Scenarios

| Scenario | File | What it shows |
|---|---|---|
| T1 plan my day | `scenarios/t1_plan_my_day.json` | Schedule agent reads the image, the user corrects one end time, Route+ETA plans Home → first class → second class → Home with every suitable route and leave-by times |
| T2 running late | `scenarios/t2_running_late.json` | At 09:40 no route reaches Boelter Hall by 10:00; the planner returns 8 routes, all marked "arrives late" |
| T3 share with Mom | `scenarios/t3_share_with_mom.json` | Share agent creates an ETA-only share, Transit reports an 8-minute delay, the share is updated and ends on arrival |

Requirements for each scenario: [requirements.md §5](../requirements.md#5-trace-scenarios).

## Runs

Not run yet. Run each scenario 3 times, since a 12B model doesn't behave the same every run:

```bash
python -m bus_agent.main scenarios/t1_plan_my_day.json --runs 3
python -m bus_agent.main scenarios/t2_running_late.json --runs 3
python -m bus_agent.main scenarios/t3_share_with_mom.json --runs 3
python -m bus_agent.checks traces/*.json
```

After changing a check, `python -m bus_agent.checks --rescore traces/*.json` re-scores the saved traces.
