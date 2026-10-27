# CS239 bus-agent (Zihan Chen)

A multi-agent public-transit assistant for a UCLA student, built for CS 239 (Fall 2026). Five LLM agents (Concierge, Schedule, Transit, Route+ETA, Share) read a class schedule, plan every suitable walking + bus/Metro route between classes, re-plan on delays, and share live travel status with a trusted contact.

The repository follows the course submission guidelines: each top-level folder is one archive.

| Folder | Archive | Contents |
|---|---|---|
| [bus-agent/](bus-agent) | `{name}-bus-agent-{uid}-requirements.tar.gz` | Application description: [app.md](bus-agent/app.md), [policy.md](bus-agent/policy.md) (P1–P21), [tools.md](bus-agent/tools.md), [agents/](bus-agent/agents) (agent1–5 with their system prompts), [episodes/](bus-agent/episodes) (example1–3, the three recorded traces) |
| [src/](src) | `{name}-bus-agent-{uid}-whole.tar.gz` | Source code and requirements: [README.md](src/README.md) (setup and run), [requirements.md](src/requirements.md), the code, [tests/](src/tests), data, scenarios and [traces/](src/traces) (raw JSON traces and the [README](src/traces/README.md) naming the policy each scenario triggered) |

Build both archives (they hold only tracked files, so `.env` and `src/data/local/` stay out; the `.tar.gz` files are gitignored):

```bash
python make_archives.py <name> <uid>
```

Quick start (details in [src/README.md](src/README.md)):

```bash
cd src
cp .env.example .env
python -m bus_agent.web
```

**Status:** the three submitted traces (one per scenario) are compliant on every checked policy. P4 (one share per confirmation), P5, P13 and P15 are enforced by guards in the code; the first, unguarded version broke P13 and P15, and [src/traces/README.md](src/traces/README.md#what-makes-these-runs-compliant) explains what changed.

License: [MIT](LICENSE).
