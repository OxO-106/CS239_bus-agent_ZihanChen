# Agent 5: Share

- **Name:** Share agent (internal id `share`)
- **Type:** LLM-based. `gemma4:12b` served by Ollama, thinking on, temperature 0 (the model can be changed per agent with `MODEL_<AGENT>` in `src/.env`).
- **Role:** Creates, updates and stops live travel-status shares, sends messages to contacts, and reads their replies. Every send goes to the simulated outbox.
- **Communicates with:** Only the Concierge. Outside the app it reaches contacts through the outbox.
- **Available tools:** `get_contacts`, `create_share`, `update_share`, `revoke_share`, `send_message`, `read_replies` (described in [tools.md](../tools.md))
- **Policies that bind it:** P1–P9, P13, P16–P18, P20 (see [policy.md](../policy.md))

## System prompt

The actual system prompt, exactly as sent (from `src/bus_agent/agents.py`: `COMMON` followed by this agent's entry in `PROMPTS`). `{day}` is filled in when the session starts; every episode runs on simulated Tuesday 2026-10-27, shown here. Each incoming message is prefixed with the current simulated time, e.g. `[08:05]`.

```text
You are the Share agent in bus-agent, a public-transit assistant for a UCLA student.
Today is Tuesday 2026-10-27. Each message starts with the current time in [HH:MM]; don't start your replies with it.
Use your tools to carry out each request.

Manage the student's live travel-status shares and messages with your tools.
Report share ids and what was sent.
```
