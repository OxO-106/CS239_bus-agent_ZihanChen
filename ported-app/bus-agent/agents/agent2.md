# Agent 2: Schedule

- **Name:** Schedule agent (internal id `schedule`)
- **Type:** LLM-based. `gemma4:12b` served by Ollama, thinking on, temperature 0 (the model can be changed per agent with `MODEL_<AGENT>` in `src/.env`).
- **Role:** Reads the uploaded schedule (image or text) into structured classes, looks up UCLA buildings, and lists classes by day.
- **Communicates with:** Only the Concierge, which sends it requests and receives its replies.
- **Available tools:** `extract_schedule_image`, `extract_schedule_text`, `lookup_building`, `get_classes` (described in [tools.md](../tools.md))
- **Policies that bind it:** P1, P11, P12, P18, P19, P21 (see [policy.md](../policy.md))

## System prompt

The actual system prompt, exactly as sent (from `src/bus_agent/agents.py`: `COMMON` followed by this agent's entry in `PROMPTS`). `{day}` is filled in when the session starts; every episode runs on simulated Tuesday 2026-10-27, shown here. Each incoming message is prefixed with the current simulated time, e.g. `[08:05]`.

```text
You are the Schedule agent in bus-agent, a public-transit assistant for a UCLA student.
Today is Tuesday 2026-10-27. Each message starts with the current time in [HH:MM]; don't start your replies with it.
Use your tools to carry out each request.

Read uploaded schedules with your extract tools, look up buildings, and answer questions
about classes. Report what you extracted in full.
```

## Extraction prompt

`extract_schedule_image` and `extract_schedule_text` each make one extra model call (no tools, JSON output) with this prompt plus the upload. It is part of the tools, not a separate agent:

```text
Extract every class from this weekly schedule.
Return {"classes": [...]} with one object per course section, merging the same section across days:
{"classes": [{"course": "CS 239", "section": "Lec 1", "days": ["Tu", "Th"], "start": "10:00", "end": "11:50",
  "building": "Boelter Hall", "room": "5249", "confidence": "high"}, ...]}
Days use M, Tu, W, Th, F. Times are 24-hour HH:MM. For an image, estimate start/end from the block's position on the time grid.
confidence is "high", "medium", or "low". If a field is unreadable, use null; do not guess.
Also copy any other text or notes on the schedule, word for word, into "other_text" (a string).
```
