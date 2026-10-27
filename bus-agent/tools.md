ask_user: Inputs: `question` (string). Returns: the user's answer as a string (in a scenario run, the next scripted answer). Used by: Concierge.

ask_schedule_agent: Inputs: `request` (string). Returns: the Schedule agent's reply text, followed by the raw results of the tools it called. Used by: Concierge.

ask_transit_agent: Inputs: `request` (string). Returns: the Transit agent's reply text, followed by the raw results of the tools it called. Used by: Concierge.

ask_route_agent: Inputs: `request` (string). Returns: the Route+ETA agent's reply text, followed by the raw results of the tools it called. Used by: Concierge.

ask_share_agent: Inputs: `request` (string). Returns: the Share agent's reply text, followed by the raw results of the tools it called. Used by: Concierge.

extract_schedule_image: Inputs: `upload_id` (string, e.g. "u1") of an uploaded schedule image. Returns: `{"classes": [{course, section, days, start, end, building, room, confidence}], "other_text"}` from one vision-model call, or an error if there is no such image. Used by: Schedule.

extract_schedule_text: Inputs: `upload_id` (string) of an uploaded schedule text (pasted or .txt). Returns: the same `{"classes": [...], "other_text"}` structure from one model call, or an error. Used by: Schedule.

lookup_building: Inputs: `name` (string), a UCLA building. Returns: `{building, lat, lon}` from the building table, or an error listing the known buildings. Used by: Schedule.

get_classes: Inputs: `day` (M, Tu, W, Th or F). Returns: `{day, classes}` from the extracted schedule, or an error if nothing has been extracted yet. Used by: Schedule.

list_routes: Inputs: `stop` (string, e.g. "Sepulveda & Pico"). Returns: `{stop, matched_stops, lines}`, the matching GTFS stops and every line that serves them. Used by: Transit.

get_schedule: Inputs: `line` (e.g. CC6R, M761), `stop` (a stop name, or a saved place or UCLA building such as "Home", which uses the line's nearest stop). Returns: `{line, stop, near, departures}`, the next 5 scheduled departures today as HH:MM (`near` names the place when one was given), or an error for an unknown line, a stop the line doesn't serve, or no matching stop. Used by: Transit.

get_realtime_arrivals: Inputs: `line`, `stop` (as for `get_schedule`). Returns: `{line, stop, near, departures, realtime: true, delay_min}`, the next 5 departures shifted by the line's current delay, or the same errors as `get_schedule`. Used by: Transit.

get_service_alerts: Inputs: `line` (optional). Returns: `{alerts, delays}`, the active alerts (`id`, `text`, `lines`, `closed_stops`) and per-line delays, for all lines if none is given. Used by: Transit.

list_places: Inputs: none. Returns: `{places, buildings}`, the saved places with their `sensitive` flag and the names of all UCLA buildings. Used by: Route+ETA.

geocode: Inputs: `name` (string), a saved place or UCLA building. Returns: `{name, lat, lon}`, or an error for an unknown place. Used by: Route+ETA.

walk_time: Inputs: `origin`, `destination` (places or buildings). Returns: `{origin, destination, walk_min}`, the walking time in whole minutes. Used by: Route+ETA.

plan_routes: Inputs: `origin`, `destination`, optional `arrive_by` (HH:MM), `depart_after` (HH:MM, default now), `max_walk` (minutes, default 10). Returns: `{summary, origin, destination, arrive_by, count, routes, excluded}`: `summary` has one line per route with its stops, leave-by time and departures (each route's own times, for the Route+ETA agent to copy), then every suitable walk + bus/Metro route (`route_id`, lines, legs, walk minutes, 2 next departures with arrivals, `leave_by`, labels) and each excluded route with its reason. Used by: Route+ETA.

compare_options: Inputs: none. Returns: `{origin, destination, changes}`, each route of the previous plan for the same trip marked kept, changed, dropped (with reason) or new, or an error if there is no earlier plan. Used by: Route+ETA.

compute_eta: Inputs: `route_id` (from a `plan_routes` result), and an optional `depart` (HH:MM), the departure the rider takes (with the P13 guard, the default). Returns: `{route_id, computed_at, depart, eta, delay_min, destination, trip_depart}` (`trip_depart`, the rider's scheduled departure, only when it answers for the rider's trip; `depart` moves with delays) for the rider's boarded trip on that route, else the chosen `depart`, otherwise the next departure, including real-time delays. Used by: Route+ETA.

get_contacts: Inputs: none. Returns: `{contacts}`, each with name, channel, `trusted` flag and note. Used by: Share.

create_share: Inputs: `recipient` (contact key or address), booleans `live_location`, `route`, `eta`, `precision` (exact, street or neighborhood), `duration_min`, `stop_on_arrival`, `message`, `eta_time` (HH:MM), `hide_places` (boolean, default false; true when the user doesn't want places named). Returns: the new share record (`share_id`, `recipient`, `fields`, `precision`, `place_names` (false when `hide_places` was set), `expires_at`, `stop_on_arrival`, `status`), after sending the first update to the outbox. With the default guards, it returns an error and sends nothing if the recipient already has an active share from the agents (P4: one confirmation, one share; use `update_share`, or `revoke_share` first), if `message` names a planned line without the route field, or, with `hide_places`, a planned stop or trip end (P5), or if an ETA share's ETA, or any time in `message`, isn't `compute_eta` for the rider's trip (P13); a missing `eta_time` is filled in. Used by: Share.

update_share: Inputs: `share_id`, optional `message`, `eta_time`. Returns: `{sent, share_status}` after sending an update with the share's fields to its recipient, or an error for an unknown share. With the default guards, the same P5 and P13 checks as `create_share`. Used by: Share.

revoke_share: Inputs: `share_id`. Returns: the share record with `status: "revoked"`, or an error for an unknown share. Used by: Share.

send_message: Inputs: `recipient`, `text`. Returns: the outbox entry for the text message. With the default guards, it returns an error and sends nothing if `text` names the line, or a place, that the recipient's active shares don't include (P5). Used by: Share.

read_replies: Inputs: none. Returns: `{replies}`, the contacts' new replies (`from`, `text`, `at`), which are then marked read. Used by: Share.
