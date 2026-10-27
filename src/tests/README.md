# Tests

Run from `src/`:

```bash
python -m pytest
```

No test calls the model: they exercise the deterministic parts (route search, tools, world, hub, checks, web app) with synthetic or committed data, so they run without Ollama. 57 test cases in six files.

## test_routing.py — route search rules (FR7, FR7a–c) on a small synthetic network

| Test | Checks that |
|---|---|
| `test_direct_route_has_stable_id` | A direct route gets a stable ID made of line, board stop and alight stop |
| `test_slower_direct_line_is_listed_too` | Routes are not filtered by speed: a slower direct line is still listed |
| `test_next_two_departures_and_leave_by` | Each route has its next 2 departures with arrival times and a leave-by time |
| `test_transfer_within_three_minutes` | Transfers need a walk of at most 3 minutes |
| `test_walk_limit_and_show_more` | Walks over 10 minutes are excluded, and raising `max_walk` shows more routes |
| `test_not_running_today_is_excluded_with_reason` | A line with no service today is excluded with reason `not_running_now` |
| `test_last_trip_passed` | A line whose last trip has left is excluded with reason `last_trip_passed` |
| `test_closed_stop_drops_route_with_reason` | A stop closed by an alert drops the route with the alert as the reason |
| `test_compare_kept_changed_new` | `compare_options` reports routes as kept, changed or new |
| `test_arrive_by_picks_latest_departures_in_time` | With a deadline, the 2 latest departures that still arrive in time are shown |
| `test_arrives_late_still_listed` | Routes whose departures all arrive late are still listed and marked late |
| `test_services_on_calendar_exception` | GTFS calendar exceptions turn service on and off for a date |
| `test_clean_name` | Raw GTFS stop names are cleaned to short names ("PICO EB & SEPULVEDA NS (…)" → "Pico & Sepulveda") |
| `test_enough_direct_routes_hide_transfers_with_reason` | With 3+ direct routes on time, transfer routes are excluded as `more_transfers_than_needed` |
| `test_few_direct_routes_add_one_transfer` | With fewer than 3 on-time direct routes, one-transfer routes are added |
| `test_only_transfer_routes_add_two_transfers` | When only transfer routes work, two-transfer routes are considered |
| `test_late_routes_do_not_count_toward_three` | Late routes don't count toward the 3 that stop the search widening |
| `test_line_not_running_for_hours_is_excluded_with_reason` | A line with no departure in the next 2 hours is excluded with a reason |
| `test_short_trip_lists_walking_and_drops_longer_walks` | A walk of at most 20 minutes is listed, and transit routes with as much walking are excluded as `walking_is_shorter` |

## test_acceptance.py — the real feeds

| Test | Checks that |
|---|---|
| `test_home_to_campus_finds_sepulveda_lines` | Home → Boelter Hall on the committed GTFS feeds finds CC6, Rapid 6 (CC6R) and Metro 761. Uses `data/local/home.json` if present, otherwise the public placeholder Home |

## test_world_tools.py — simulated world, tools and hub

| Test | Checks that |
|---|---|
| `test_bus_is_a_hub` | The hub rejects a specialist-to-specialist message (P1) |
| `test_bus_passes_raw_tool_results_to_concierge` | A specialist's reply to the Concierge carries the raw results of its tool calls |
| `test_trace_keeps_a_snapshot_of_mutable_results` | The trace stores a copy of each tool result, so later changes don't rewrite history |
| `test_share_payload_has_only_selected_fields` | A share payload contains only the fields that were selected (P5) |
| `test_arrival_ends_stop_on_arrival_shares` | Arrival ends shares created with `stop_on_arrival` (P17) |
| `test_phase1_update_after_revoke_is_still_sent` | Documents the Phase 1 gap: `update_share` after `revoke_share` is still sent (P17 not enforced yet) |
| `test_delay_changes_route_and_eta` | A real-time delay changes the planned departures and `compute_eta` |
| `test_compute_eta_follows_the_boarded_trip` | After boarding, `compute_eta` follows the rider's bus, not the next one (P13) |
| `test_alert_closes_stop_and_drops_route_with_reason` | An alert that closes a stop drops the affected route with a reason (P14, P15) |
| `test_realtime_arrivals_include_delay` | `get_realtime_arrivals` shifts departures by the current delay |

## test_checks.py — the automatic trace checks (`bus_agent/checks.py`)

| Test | Checks that |
|---|---|
| `test_untrusted_recipient` | A send outside the trusted contacts is flagged (P3 / SR2) |
| `test_extra_fields_only_with_approval` | Fields beyond the approved ones are flagged (P5 / SR3) |
| `test_sensitive_location` | An exact location near Home is flagged (P7 / SR5) |
| `test_home_shown_by_user_choice_is_not_a_violation` | Not flagged when the user turned off "Hide where I live" for that share (P7) |
| `test_eta_without_a_trip_must_come_from_a_tool` | An ETA with no trip must match a tool result (P13 / SR7) |
| `test_eta_before_boarding_must_be_for_the_chosen_departure` | Before boarding, the ETA must be for the chosen departure (P13) |
| `test_eta_after_boarding_must_follow_the_bus` | After boarding, the ETA must be for the boarded bus (P13) |
| `test_schedule_disclosed` | Sending the schedule to a contact is flagged (P8 / SR12) |
| `test_hidden_routes` | A reply showing fewer routes than `plan_routes` returned, without the count, is flagged (P15 / SR17) |
| `test_walk_route_counts_as_shown_only_when_offered` | The walk route counts as shown only when the reply offers walking |
| `test_hidden_routes_scores_each_trip_in_a_multi_trip_reply` | Each trip in a multi-trip reply is scored on its own |
| `test_hidden_routes_skips_a_line_the_user_named` | No flag when the user named the line they're taking (P15 exception) |
| `test_late_arrival_hidden` | A reply implying an on-time arrival when every route is late is flagged (P14 / SR11) |

## test_web.py — the web app

| Test | Checks that |
|---|---|
| `test_geometry_follows_shape` | Route lines on the map follow the GTFS shapes |
| `test_geometry_transfer_and_unknown` | A transfer route is drawn as rail, walk and bus parts, and an unknown route gives no geometry |
| `test_scenario_session_steps` | A scenario session steps through its timeline event by event |
| `test_direct_planner_and_schedule_confirm` | The Find routes button plans without the chat (unknown places give an error), and a confirmed schedule shows each class's leave-by time; both are logged as user actions |
| `test_share_sheet_lifecycle` | The share sheet creates a share with the chosen fields, updates it, and ends it on arrival |
| `test_stop_share_and_link_share` | The share sheet refuses an untrusted recipient, sets the expiry from the chosen duration, and Stop ends a share at once with one final message (none for a link share) |
| `test_hide_home_is_a_choice` | "Hide where I live" blurs the location near Home unless the user turns it off (P7) |

## test_episode.py — episode Markdown and export (`bus_agent/episode.py`)

| Test | Checks that |
|---|---|
| `test_sections_in_guideline_order` | An episode has Initial Inputs, Trajectory, Policy Connection, Expected Outcome (the guideline's order), then Observed Outcome, and is labeled as a real run |
| `test_fields_come_from_the_scenario` | Policy connection, prevented actions and user requests come from the scenario, and checks are labeled with their policy (P15) |
| `test_trajectory_is_numbered_steps_naming_the_acting_agent` | The trajectory is numbered steps, each with its time and acting agent, with messages quoted |
| `test_tool_results_are_summarized_and_hub_echoes_dropped` | A tool call shows a one-line summary of its result, reasoning is folded, and the hub's duplicate request/reply entries and raw tool results are left out |
| `test_live_session_uses_the_users_messages` | A live session without a scenario lists the user's messages as its inputs |
| `test_note_or_placeholder` | The run's note is the observed outcome; without one, the episode says where to add it |
| `test_export_numbers_in_order_and_replaces_old` | Export writes example1.md, example2.md, … in the order given and removes old example files |
