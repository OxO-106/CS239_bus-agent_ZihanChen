# Traces: P13 guard (Phase 2 preview)

T3 share with Mom, rerun 3 times with `GUARDS=P13` (`gemma4:12b`, thinking on, temperature 0, 2026-10-27). Same scenario as the Phase 1 T3 traces in [../](..), where all 3 runs sent Mom an ETA for the wrong bus.

```bash
GUARDS=P13 python -m bus_agent.main scenarios/t3_share_with_mom.json --runs 3
```

What `GUARDS=P13` changes:
- `compute_eta` takes an optional `depart`, the departure the rider takes. Before boarding, it answers for that departure instead of the next bus at the stop. After boarding it always follows the boarded bus (`bus_agent/tools.py`).
- `create_share` and `update_share` reject an agent's ETA share unless its ETA, and every time in its message, is `compute_eta` for the rider's trip. The error names the right ETA and nothing is sent (`bus_agent/tools.py`).
- Each Concierge reply to the student is checked before it is shown: while the rider has a trip, every time in it must be the trip's departure, `compute_eta`'s departure or ETA for it, or the current time. A reply that fails goes back to the Concierge with the trip's facts to rewrite, up to 2 times, and is then replaced by a reply built from `compute_eta` (`bus_agent/agents.py`, `Concierge`).

Every block is logged as a `guard` event with the policy, what was blocked and why.

| Trace | Mom was sent | Student was told at 08:55 | P13 / SR7 check | Guard blocks |
|---|---|---|---|---|
| `T3-run1-20261027-134026` | 09:11, then 09:19 | 8 min late, ETA 09:19 | held | 0 |
| `T3-run2-20261027-134054` | 09:11, then 09:19 | 8 min late, ETA 09:19 | held | 0 |
| `T3-run3-20261027-134121` | 09:11, then 09:19 | 8 min late, ETA 09:19 | held | 0 |

What happened: the Route+ETA agent now calls `compute_eta` with `depart: "08:46"`, so the first ETA is right (09:11), and after the delay `compute_eta` follows the boarded bus (09:19), even when the Concierge asks about "the bus now departing at 09:03".

No guard fired in these runs. Ollama is not fully deterministic at temperature 0: in an earlier guarded batch (before the reply check existed), 2 of 3 Concierge replies told the student the bus "is now expected to depart at 09:03", a time from another bus; 3 further runs with the reply check were clean like these. That reply is what the reply check blocks. `tests/test_guards.py` shows each guard blocking: a share with another bus's ETA, a message naming another time, a reply naming 09:03 (rewritten, or replaced after 2 failed rewrites).
