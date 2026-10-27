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

get_schedule: Inputs: `line` (e.g. CC6R, M761), `stop` (string). Returns: `{line, stop, departures}`, the next 5 scheduled departures today as HH:MM, or an error if no stop matches. Used by: Transit.

get_realtime_arrivals: Inputs: `line`, `stop`. Returns: `{line, stop, departures, realtime: true, delay_min}`, the next 5 departures shifted by the line's current delay. Used by: Transit.

get_service_alerts: Inputs: `line` (optional). Returns: `{alerts, delays}`, the active alerts (`id`, `text`, `lines`, `closed_stops`) and per-line delays, for all lines if none is given. Used by: Transit.

list_places: Inputs: none. Returns: `{places, buildings}`, the saved places with their `sensitive` flag and the names of all UCLA buildings. Used by: Route+ETA.

geocode: Inputs: `name` (string), a saved place or UCLA building. Returns: `{name, lat, lon}`, or an error for an unknown place. Used by: Route+ETA.

walk_time: Inputs: `origin`, `destination` (places or buildings). Returns: `{origin, destination, walk_min}`, the walking time in whole minutes. Used by: Route+ETA.

plan_routes: Inputs: `origin`, `destination`, optional `arrive_by` (HH:MM), `depart_after` (HH:MM, default now), `max_walk` (minutes, default 10). Returns: `{origin, destination, arrive_by, count, routes, excluded}`, every suitable walk + bus/Metro route (`route_id`, lines, legs, walk minutes, 2 next departures with arrivals, `leave_by`, labels) and each excluded route with its reason. Used by: Route+ETA.

compare_options: Inputs: none. Returns: `{origin, destination, changes}`, each route of the previous plan for the same trip marked kept, changed, dropped (with reason) or new, or an error if there is no earlier plan. Used by: Route+ETA.

compute_eta: Inputs: `route_id` (from a `plan_routes` result). Returns: `{route_id, computed_at, depart, eta, delay_min, destination}` for the rider's boarded trip on that route, otherwise for the next departure, including real-time delays. Used by: Route+ETA.

get_contacts: Inputs: none. Returns: `{contacts}`, each with name, channel, `trusted` flag and note. Used by: Share.

create_share: Inputs: `recipient` (contact key or address), booleans `live_location`, `route`, `eta`, `precision` (exact, street or neighborhood), `duration_min`, `stop_on_arrival`, `message`, `eta_time` (HH:MM). Returns: the new share record (`share_id`, `recipient`, `fields`, `precision`, `expires_at`, `stop_on_arrival`, `status`), after sending the first update to the outbox. Used by: Share.

update_share: Inputs: `share_id`, optional `message`, `eta_time`. Returns: `{sent, share_status}` after sending an update with the share's fields to its recipient, or an error for an unknown share. Used by: Share.

revoke_share: Inputs: `share_id`. Returns: the share record with `status: "revoked"`, or an error for an unknown share. Used by: Share.

send_message: Inputs: `recipient`, `text`. Returns: the outbox entry for the text message. Used by: Share.

read_replies: Inputs: none. Returns: `{replies}`, the contacts' new replies (`from`, `text`, `at`), which are then marked read. Used by: Share.
