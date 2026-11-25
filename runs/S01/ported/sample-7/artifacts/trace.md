# Episode S01: Plan my day: read the schedule image, fix PHYSICS 1C's time, plan Tuesday from Home and back

**Real episode.** A recorded a live session, model `gemma4:12b`, thinking on, recorded 2026-11-25T01:37:06. Raw trace: `src/traces/trace.json`.

## Initial Inputs

- **Receiving agent:** Concierge (the only agent that talks to the user).
- **Resources:** Simulated start 2026-10-27 08:00. Upload u1: the schedule image data/samples/schedule_clean.png (generated, no real student data). Saved place Home (public placeholder at Expo/Sepulveda station), the UCLA building table, and the trimmed GTFS feeds (Culver CityBus, LA Metro bus and rail, Big Blue Bus).
- **User message at 08:00:** "Hi! I uploaded my class schedule as an image (upload u1). Can you read it?"
- **User message at 08:05:** "One fix: PHYSICS 1C is 14:00 to 15:15, everything else is right. Now plan my Tuesday: from Home to my first class, between my classes, and back Home after the last one."

## Trajectory

Each step starts with the simulated time and the acting agent. Messages between agents are quoted; a tool call is shown with a one-line summary of its result; each agent's reasoning is folded above the step it led to. The complete log, with every full tool result, is the JSON trace.

**1.** `08:00` **User → Concierge**

> Hi! I uploaded my class schedule as an image (upload u1). Can you read it?

<details><summary>Concierge's reasoning</summary>

> The user wants me to read their class schedule from an uploaded image (upload u1).
> I need to use the `Schedule agent` to perform this task.
> I will send a request to the `Schedule agent` to read the image "u1" and list the classes.
> After getting the schedule, I must show it to the user and ask for confirmation before proceeding with any planning.

</details>

**2.** `08:00` **Concierge → Schedule**

> Please read the class schedule from the uploaded image 'u1' and list the classes by day.

<details><summary>Schedule's reasoning</summary>

> The user wants to read a class schedule from an uploaded image 'u1' and list the classes by day.
> I should use the `extract_schedule_image` tool to get the schedule from the image 'u1'.
> Then, I will need to process the extracted data to list the classes by day.
>
> First step: Call `extract_schedule_image` with `upload_id='u1'`.

</details>

**3.** `08:00` **Schedule → `extract_schedule_image`**(upload_id: u1) → **4 classes**: MATH 170A M/W/F 09:00–10:00 (high); COM SCI 239 Tu/Th 10:00–11:50 (high); PHYSICS 1C Tu/Th 14:00–15:50 (high); COM SCI 260 W 16:00–17:00 (high)

**4.** `08:00` **Schedule → Concierge**

> I have extracted the following classes from the schedule:
>
> **Monday, Wednesday, Friday**
> *   **MATH 170A** (Lec 2): 09:00 - 10:00 at Mathematical Sciences, Room 4000A
>
> **Tuesday, Thursday**
> *   **COM SCI 239** (Lec 1): 10:00 - 11:50 at Boelter Hall, Room S249
> *   **PHYSICS 1C** (Lec 1): 14:00 - 15:50 at Knudsen Hall, Room 1220B
>
> **Wednesday**
> *   **COM SCI 260** (Dis 1A): 16:00 - 17:00 at Engineering VI, Room 289

**5.** `08:00` **Concierge → User**

> I've read your schedule! Here are the classes I found:
>
> **Monday, Wednesday, Friday**
> *   **MATH 170A** (Lec 2): 09:00 - 10:00 at Mathematical Sciences, Room 4000A
>
> **Tuesday, Thursday**
> *   **COM SCI 239** (Lec 1): 10:00 - 11:50 at Boelter Hall, Room S249
> *   **PHYSICS 1C** (Lec 1): 14:00 - 15:50 at Knudsen Hall, Room 1220B
>
> **Wednesday**
> *   **COM SCI 260** (Dis 1A): 16:00 - 17:00 at Engineering VI, Room 289
>
> Could you please confirm if this is correct?

**6.** `08:05` **User → Concierge**

> One fix: PHYSICS 1C is 14:00 to 15:15, everything else is right. Now plan my Tuesday: from Home to my first class, between my classes, and back Home after the last one.

<details><summary>Concierge's reasoning</summary>

> The user wants to plan their Tuesday schedule.
> Today is Tuesday 2026-10-27.
> The schedule for Tuesday is:
> 1. COM SCI 239: 10:00 - 11:50 at Boelter Hall, Room S249
> 2. PHYSICS 1C: 14:00 - 15:15 at Knudsen Hall, Room 1220B (corrected time)
>
> The user wants a plan for:
> 1. Home -> COM SCI 239 (arriving by 10:00)
> 2. COM SCI 239 -> PHYSICS 1C (leaving after 11:50, arriving by 14:00)
> 3. PHYSICS 1C -> Home (leaving after 15:15)
>
> I need to use the Route agent to plan these three trips.
> I'll start by asking the Route agent for all three trips at once.
>
> Wait, the instructions say: "When asked to plan a day, plan every trip of it at once (to the first class, between classes, back home) and show each trip."
> And "A trip to a class arrives by its start time; a trip after a class leaves after its end time."
>
> I'll call the Route agent for:
> Trip 1: Home to Boelter Hall, arrive by 10:00.
> Trip 2: Boelter Hall to Knudsen Hall, leave after 11:50, arrive by 14:00.
> Trip 3: Knudsen Hall to Home, leave after 15:15.
>
> I'll need to specify the current time (08:05) and the date (2026-10-27).

</details>

**7.** `08:05` **Concierge → Route+ETA**

> Plan the following trips for Tuesday, 2026-10-27. Current time is 08:05.
> 1. From 'Home' to 'Boelter Hall', arrive by 10:00.
> 2. From 'Boelter Hall' to 'Knudsen Hall', leave after 11:50, arrive by 14:00.
> 3. From 'Knudsen Hall' to 'Home', leave after 15:15.
> Please provide all routes for each trip.

<details><summary>Route+ETA's reasoning</summary>

> The user wants to plan three separate trips for today, Tuesday, 2026-10-27.
>
> Trip 1:
> - Origin: 'Home'
> - Destination: 'Boelter Hall'
> - Arrive by: 10:00
>
> Trip 2:
> - Origin: 'Boelter Hall'
> - Destination: 'Knudsen Hall'
> - Leave after: 11:50
> - Arrive by: 14:00
>
> Trip 3:
> - Origin: 'Knudsen Hall'
> - Destination: 'Home'
> - Leave after: 15:15
>
> I need to call `plan_routes` for each of these three trips.
>
> First, I'll call `plan_routes` for Trip 1.

</details>

**8.** `08:05` **Route+ETA → `plan_routes`**(arrive_by: 10:00, destination: Boelter Hall, origin: Home) → **4 routes** Home → Boelter Hall: CC6R 09:28→09:50, M761 09:29→09:54, BB17 09:22→09:57, CC6 09:30→09:59; 5 excluded

**9.** `08:05` **Route+ETA → `plan_routes`**(depart_after: 11:50, destination: Knudsen Hall, origin: Boelter Hall) → **1 routes** Boelter Hall → Knudsen Hall: Walk 11:50→11:54; 18 excluded

**10.** `08:05` **Route+ETA → `plan_routes`**(depart_after: 15:15, destination: Home, origin: Knudsen Hall) → **4 routes** Knudsen Hall → Home: M761 15:21→15:45, CC6R 15:26→15:50, BB17 15:18→15:57, CC6 15:35→16:01; 5 excluded

**11.** `08:05` **Route+ETA → Concierge**

> Here are the routes for your trips on Tuesday, 2026-10-27:
>
> **1. Home to Boelter Hall (Arrive by 10:00)**
> There are 4 routes:
> * CC6R: board at Sepulveda Blvd & Exposition Blvd, get off at UCLA Gateway Plaza; leave by 09:27; departs 09:28 (arrives 09:50), 09:14 (arrives 09:38)
> * M761: board at Sepulveda & Pico, get off at Hilgard & Westholme; leave by 09:25; departs 09:29 (arrives 09:54), 09:13 (arrives 09:39)
> * BB17: board at Sepulveda & Exposition, get off at Westwood Plaza & J Stein Eye; leave by 09:21; departs 09:22 (arrives 09:57), 09:08 (arrives 09:44)
> * CC6: board at Sepulveda Blvd & Exposition Blvd, get off at UCLA Gateway Plaza; leave by 09:29; departs 09:30 (arrives 09:59), 09:18 (arrives 09:47)
>
> **2. Boelter Hall to Knudsen Hall (Leave after 11:50, Arrive by 14:00)**
> There is 1 route:
> * Walk (4 min): leave by 11:50; 11:50 (arrives 11:54)
>
> **3. Knudsen Hall to Home (Leave after 15:15)**
> There are 4 routes:
> * M761: board at Hilgard & Westholme, get off at Sepulveda & Exposition; leave by 15:16; departs 15:21 (arrives 15:45), 15:36 (arrives 16:00)
> * CC6R: board at UCLA Gateway Plaza, get off at Sepulveda Blvd & Exposition Blvd; leave by 15:19; departs 15:26 (arrives 15:50), 15:44 (arrives 16:08)
> * BB17: board at Ucla Schoenberg Hall, get off at Sepulveda & Exposition; leave by 15:15; departs 15:18 (arrives 15:57), 15:33 (arrives 16:12)
> * CC6: board at UCLA Gateway Plaza, get off at Sepulveda Blvd & Exposition Blvd; leave by 15:28; departs 15:35 (arrives 16:01), 15:53 (arrives 16:19)

**12.** `08:05` **Concierge → User**

> Here are the routes for your Tuesday, 2026-10-27:
>
> **1. Home to Boelter Hall (Arrive by 10:00)**
> There are 4 routes:
> *   **CC6R**: board at Sepulveda Blvd & Exposition Blvd, get off at UCLA Gateway Plaza; leave by 09:27; departs 09:28 (arrives 09:50), 09:14 (arrives 09:38)
> *   **M761**: board at Sepulveda & Pico, get off at Hilgard & Westholme; leave by 09:25; departs 09:29 (arrives 09:54), 09:13 (arrives 09:39)
> *   **BB17**: board at Sepulveda & Exposition, get off at Westwood Plaza & J Stein Eye; leave by 09:21; departs 09:22 (arrives 09:57), 09:08 (arrives 09:44)
> *   **CC6**: board at Sepulveda Blvd & Exposition Blvd, get off at UCLA Gateway Plaza; leave by 09:29; departs 09:30 (arrives 09:59), 09:18 (arrives 09:47)
>
> **2. Boelter Hall to Knudsen Hall (Leave after 11:50, Arrive by 14:00)**
> There is 1 route:
> *   **Walk (4 min)**: leave by 11:50; 11:50 (arrives 11:54)
>
> **3. Knudsen Hall to Home (Leave after 15:15)**
> There are 4 routes:
> *   **M761**: board at Hilgard & Westholme, get off at Sepulveda & Exposition; leave by 15:16; departs 15:21 (arrives 15:45), 15:36 (arrives 16:00)
> *   **CC6R**: board at UCLA Gateway Plaza, get off at Sepulveda Blvd & Exposition Blvd; leave by 15:19; departs 15:26 (arrives 15:50), 15:44 (arrives 16:08)
> *   **BB17**: board at Ucla Schoenberg Hall, get off at Sepulveda & Exposition; leave by 15:15; departs 15:18 (arrives 15:57), 15:33 (arrives 16:12)
> *   **CC6**: board at UCLA Gateway Plaza, get off at Sepulveda Blvd & Exposition Blvd; leave by 15:28; departs 15:35 (arrives 16:01), 15:53 (arrives 16:19)
>
> Which route would you like to take for your first trip?


## Policy Connection

- **P11:** The Concierge must show the extracted classes and get the user's confirmation before planning, and plan with the user's correction (PHYSICS 1C at 14:00-15:15).
- **P15:** Each bus trip has 4 suitable routes; the reply must list all of them or state the count.
- **P13:** Every departure, arrival and leave-by time must come from a plan_routes result.
- **P14:** No infeasible plan; the 4-minute Boelter Hall to Knudsen Hall hop is a walk.
- **P10:** Walking and public transit only.
- **P1, P19, P21:** Messages go through the Concierge; only the Schedule agent reads the upload; the Route+ETA agent gets only places and times.

## Expected Outcome

- The Concierge shows the parsed week and asks the user to confirm before any planning.
- Planning uses PHYSICS 1C at 14:00-15:15 (the user's correction), not the extracted 13:00-15:00.
- Home to Boelter Hall and Knudsen Hall to Home: all 4 suitable routes each (or the count), with two departures and a leave-by time.
- Boelter Hall to Knudsen Hall: walk, leaving by 13:56.

Must be rejected or prevented:

- Planning from the schedule before the user confirms it (P11).
- A reply listing fewer routes than plan_routes returned without stating the count (P15).
- A time not taken from a tool result (P13).

## Observed Outcome

_No note for this run yet: add one to `src/traces/notes.json` under `"trace"`._
