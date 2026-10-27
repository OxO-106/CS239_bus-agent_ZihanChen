ask_user: (Concierge) Takes `question` (string); shows it to the user in the chat and returns the user's answer as a string (in a scenario run, the next scripted answer).
ask_schedule_agent: (Concierge) Takes `request` (string); delivers it to the Schedule agent through the hub and returns that agent's reply text followed by the raw results of the tools it called.
ask_transit_agent: (Concierge) Takes `request` (string); delivers it to the Transit agent through the hub and returns its reply text plus the raw results of the tools it called.
ask_route_agent: (Concierge) Takes `request` (string); delivers it to the Route+ETA agent through the hub and returns its reply text plus the raw results of the tools it called.
ask_share_agent: (Concierge) Takes `request` (string); delivers it to the Share agent through the hub and returns its reply text plus the raw results of the tools it called.
extract_schedule_image: (Schedule) Takes `upload_id` (e.g. "u1") of an uploaded schedule image; runs one vision-model call and returns `{"classes": [{course, section, days, start, end, building, room, confidence}], "other_text"}`, or an error if there is no such image upload.
extract_schedule_text: (Schedule) Takes `upload_id` of an uploaded schedule text (pasted or .txt); runs one model call and returns the same `{"classes": [...], "other_text"}` structure, or an error.
lookup_building: (Schedule) Takes `name` of a UCLA building; returns `{building, lat, lon}` from the building table, or an error listing the known buildings.
get_classes: (Schedule) Takes `day` (M, Tu, W, Th or F); returns `{day, classes}` from the extracted schedule, or an error if nothing has been extracted yet.
list_routes: (Transit) Takes `stop` (stop name, e.g. "Sepulveda & Pico"); returns the matched GTFS stop names and every line that serves them.
get_schedule: (Transit) Takes `line` (e.g. CC6R, M761) and `stop`; returns the next 5 scheduled departures of that line at that stop today (HH:MM), or an error if no stop matches.
get_realtime_arrivals: (Transit) Takes `line` and `stop`; returns the next 5 departures shifted by the line's current real-time delay, with `realtime: true` and `delay_min`.
get_service_alerts: (Transit) Takes an optional `line`; returns the active service alerts (text, affected lines, closed stops) and current per-line delays, all lines if none is given.
list_places: (Route+ETA) Takes nothing; returns the user's saved places (each with its `sensitive` flag) and the names of all UCLA buildings.
geocode: (Route+ETA) Takes `name` of a saved place or UCLA building; returns `{name, lat, lon}`, or an error for an unknown place.
walk_time: (Route+ETA) Takes `origin` and `destination` (places or buildings); returns the walking time in whole minutes.
plan_routes: (Route+ETA) Takes `origin`, `destination`, optional `arrive_by` (HH:MM), `depart_after` (HH:MM, default now) and `max_walk` (minutes, default 10); searches the GTFS feeds and returns every suitable walk + bus/Metro route with `route_id`, lines, legs, walk minutes, 2 next departures with arrival times, leave-by time, labels and total `count`, plus the `excluded` routes with a reason each.
compare_options: (Route+ETA) Takes nothing; diffs the latest plan against the previous plan for the same trip and returns each route as kept, changed, dropped (with reason) or new, or an error if there is no earlier plan.
compute_eta: (Route+ETA) Takes `route_id` from a `plan_routes` result; returns `{route_id, computed_at, depart, eta, delay_min, destination}` for the rider's boarded trip on that route if there is one, otherwise for the next departure, including real-time delays.
get_contacts: (Share) Takes nothing; returns the user's saved contacts with name, channel, `trusted` flag and notes.
create_share: (Share) Takes `recipient` (contact key or address), booleans `live_location`, `route`, `eta`, `precision` (exact, street or neighborhood), `duration_min`, `stop_on_arrival`, `message` and `eta_time`; records a new active share, sends the first update to the outbox, and returns the share record (`share_id`, fields, precision, `expires_at`, status).
update_share: (Share) Takes `share_id`, optional `message` and `eta_time`; sends a status update with the share's fields to its recipient through the outbox and returns `{sent, share_status}`, or an error for an unknown share.
revoke_share: (Share) Takes `share_id`; marks the share revoked and returns the updated share record, or an error for an unknown share.
send_message: (Share) Takes `recipient` and `text`; puts a text message in the outbox and returns the outbox entry.
read_replies: (Share) Takes nothing; returns the contacts' new replies (sender, text, time) and marks them read.
