# bus-agent

bus-agent is a multi-agent public-transit assistant for a UCLA student. The student uploads their weekly class schedule (an image or text); the system reads it, plans walking + bus/Metro rail trips to and between classes using real LA-area timetables, keeps those plans current when buses are delayed, and can share live travel status with a trusted contact until the student arrives.

Five LLM agents work together in a hub topology: the **Concierge** talks to the user and is the only agent the specialists talk to, and four specialists each own their own tools: **Schedule** (reads the upload, looks up buildings), **Transit** (departures, real-time delays, service alerts), **Route+ETA** (every suitable route, leave-by times, ETAs, re-plans) and **Share** (contacts, live shares, messages). Route search is deterministic code over the agencies' public GTFS feeds; real-time data, contacts and sending are simulated, and everything sent goes to an outbox recorded in the trace.

## Supported tasks

- **Read a class schedule:** extract every class (course, days, times, building, room, confidence) from an uploaded image or text, show it to the user, and apply their corrections before using it.
- **Plan a day or a single trip:** "plan my Tuesday", "get me to Boelter Hall by 10:00". It lists every suitable route (walk, bus, Metro rail, up to two transfers), each with its next departures, arrival time and leave-by time, and flags gaps between classes that are too short.
- **Running late:** say when no route arrives by the deadline and give the earliest arrival.
- **React to delays and alerts:** recompute ETAs and leave-by times, re-plan, and report which routes were kept, changed, dropped or added.
- **Share live travel status:** share only the fields the user picks (ETA, route, live location at a chosen precision) with a contact, for one trip, update the share when the ETA changes, and end it on arrival, at expiry, or when the user says stop.

Files in this folder: [policy.md](policy.md) (P1–P21), [tools.md](tools.md), [agents/](agents) (one file per agent with its system prompt) and [episodes/](episodes) (nine recorded runs: example1–3 plan my day, example4–6 running late, example7–9 share with Mom).
