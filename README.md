# bus-agent

A multi-agent public-transit assistant for a UCLA student (CS 239, Fall 2026). It reads a class schedule, lists every suitable walking + bus/Metro route between classes, re-plans on delays, and can share live travel status with a trusted contact. See [plan.md](plan.md) and [requirements.md](requirements.md).

## Setup

1. Run Ollama with `gemma4:12b` on a GPU machine (`ollama pull gemma4:12b`, `OLLAMA_HOST=0.0.0.0`).
2. `cp .env.example .env` and set `OLLAMA_URL`.
3. Python 3.10+, standard library only so far.

## Bench

```bash
python -m bench.tool_calls
python -m bench.extract_schedule
```

Results: [bench/README.md](bench/README.md).
