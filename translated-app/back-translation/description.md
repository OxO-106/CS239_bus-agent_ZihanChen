# Backtranslation

Each section states recorded inputs (A), derived conditions (B), and the installed execution boundary (C).

### Concierge tool calls (`concierge-tool-calls`)
A. The host supplies the actor, tool name, and turn source before invocation. A missing Concierge source becomes concierge.
B. The Concierge may call a tool it owns; any recorded turn source is sufficient.
C. At the tool gate, missing ownership or a refusal prevents the callback; otherwise it runs.

### Specialist calls in concierge turns (`specialist-concierge-turns`)
A. The host supplies the specialist actor and tool name. A Concierge message records turn source concierge before the specialist runs.
B. The specialist may call only an owned tool, and the recorded turn source must equal concierge.
C. At the tool gate, a missing owned tool, wrong turn source, or refusal prevents the original callback.

### Share calls in app turns (`share-app-turns`)
A. The app supplies the Share agent and tool name and records turn source app before the call.
B. The Share agent may call an owned share tool when the recorded source is app.
C. At the tool gate, the callback runs only if this or another allowance holds; otherwise the call is refused.

### Route calls in app turns (`route-app-turns`)
A. The app supplies the Route agent and tool name and records turn source app before the call.
B. The Route agent may call an owned route tool when the recorded source is app.
C. At the tool gate, the callback runs only if this or another allowance holds; otherwise the call is refused.

### Schedule calls in app turns (`schedule-app-turns`)
A. The app supplies the Schedule agent and tool name and records turn source app before the call.
B. The Schedule agent may call an owned schedule tool when the recorded source is app.
C. At the tool gate, the callback runs only if this or another allowance holds; otherwise the call is refused.

### Tool ownership refusal (`tool-ownership`)
A. The call supplies an actor and tool name, and the fixed allocation names the owner of each installed tool.
B. If another agent owns the tool and the actor does not, the ownership refusal applies. Refusals override allowances; with no refusal, at least one allow condition is still required.
C. The gate calls the original tool only after that composition permits it. An allowed call may later return an application error, which is not a refusal by this layer.

### Trusted recipients (`trusted-recipients`)
A. Create and message calls supply a lowercased recipient; an update takes the recipient from the referenced share record. Trust is a saved contact field read at call time, matched only by lowercased contact ID.
B. The share, message, or update is refused when that contact does not record trusted as true. No separate unfamiliar-recipient consent is supplied.
C. The create, message, or update callback is not entered. The app's share-sheet trust check is a separate earlier check for page-created shares.

### One agent share per recipient (`one-agent-share-per-recipient`)
A. The create call supplies the recipient and a channel value; existing shares supply recipient, status, and channel at call time. A share with no channel is treated as agent-created.
B. An agent-created share is refused when any active share with no channel has the same recipient. One active share is used as a stand-in for confirmation; no confirmation record or scope exists.
C. The create callback is not entered. The app's original duplicate-share check, when its guard is enabled, runs later for channel-less shares and is not this layer's decision.

### Line requires route field (`line-requires-route`)
A. The current text supplies line mentions, matched against lines in saved plans. Create reads its route field from the call; update reads the referenced share; a message reads all active shares for the recipient.
B. A text naming a planned line is refused unless route is enabled for the new share, the updated share, or at least one active share for the message recipient.
C. At the tool-call gate, the share or message callback is not entered when the named line lacks that route field.

### Place names require enabling (`place-names-enabled`)
A. The current text supplies place mentions, matched against planned trip places and stops. Create uses its own place-name choice; update uses the share; a message uses all active shares for the recipient and checks for a prior end notice.
B. A create or update with place names off is refused when it names a place. For a message, any active share with place names off makes the recipient setting off, and no active share also refuses place names unless the request is a valid one-time end notice.
C. The share or message callback is not entered when this condition fails.

### Coordinates require live location (`coordinates-require-live-location`)
A. The current text supplies a coordinate detection. Create reads its live-location choice from the call; update reads the referenced share's enabled fields.
B. A create or update text carrying coordinates is refused when live location is not enabled.
C. The share callback is not entered when the coordinate lacks the live-location field.

### Share duration limits (`share-duration-limits`)
A. The create call supplies duration and stop-on-arrival choice. Omitted duration is recorded as -1, invalid duration as -2, and omitted stop-on-arrival defaults to true.
B. A duration above 240 minutes is refused. A missing or invalid duration is refused when stop-on-arrival is explicitly false; exactly 240 is allowed, and no duration with stop-on-arrival true is allowed.
C. The create callback is not entered when either duration condition is refused.

### Sensitive-place precision (`sensitive-place-precision`)
A. Create supplies live location, precision label, channel, and protection; update reads these from the share. Distance is read from current app GPS to saved sensitive places, with no coordinates treating distance as very large.
B. Street or exact precision is refused strictly within 300 metres of a sensitive place unless the recorded app-style protection or exact-choice flag is true. Exact maps to five decimals, street to three, and neighborhood to two.
C. The share callback is not entered when precise location is refused. A protected app share passes on its protection flag and relies on the original payload to round the sent coordinates to two decimals; this layer does not inspect the rounded output.

### Only current-trip saved places (`current-trip-saved-places`)
A. The current text is matched against saved place names. Planned origins, destinations, boarding stops, and alighting stops, including the latest plan, define places covered by the current trip.
B. Any saved place named in a create, update, or message that is outside those trip places is refused.
C. At the tool-call gate, the share or message callback is not entered when another saved place is named.

### Schedule material may not leave (`schedule-material-outbound`)
A. The current share or message text is compared with stored extraction notes and text uploads of at least 16 characters, and with extracted course names; two or more course mentions also count.
B. If schedule material appears in a create, update, or message, that outbound action is refused.
C. The share or message callback is not entered when schedule material is detected.

### Schedule material to specialists (`schedule-material-specialists`)
A. The request text sent to Transit, Route, or Share is compared with stored extraction notes and text uploads of at least 16 characters, and with extracted course names.
B. A Transit, Route, or Share-agent request containing schedule material is refused. Requests to the Schedule agent are not refused by these rules.
C. At the tool-call gate, the specialist request is not sent when schedule material is detected.

### Agent ETA share currency (`agent-eta-currency`)
A. The app supplies the rider's route and departure from a boarded or chosen trip; a chosen trip is recorded by the original compute_eta only when its existing guard is enabled. A successful compute_eta supplies a stored row containing route, ETA, departure, delay, and change counter; a later success replaces that route's row, while a failure removes nothing, and the counter never decreases.
B. For an agent share with ETA enabled, the share is refused if no rider trip exists, if the rider's route has no current stored ETA, or if that result is older than the current change counter. The route IDs must match; the rider's departure is not compared.
C. The create or update callback is not entered when this ETA condition is refused. A successful compute_eta record supports a later share decision and never retroactively authorizes the compute_eta call.

### Supplied ETA equality (`supplied-eta-equality`)
A. The create or update call may supply eta_time. The rider's route ID and the latest stored compute_eta ETA for that route are read from saved state at call time.
B. When eta_time is present, it must equal the stored ETA for the rider's route, or the agent ETA share is refused. If eta_time is omitted, this rule makes no equality decision.
C. The share callback is not entered when supplied and stored ETAs differ. Other checks still apply, and the app's original share guard may later fill or reject an omitted ETA.

### Message times within rider trip (`message-times-rider-trip`)
A. The current text supplies every HH:MM time. The rider trip supplies its departure, and a successful compute_eta row supplies its ETA and departure for the same route ID; these values form the trip's known times.
B. An agent share request is refused when it names any time outside that known set for the rider's route. This rule fires only when a rider trip exists.
C. The share or message callback is not entered when a time falls outside the rider's known times.

### Updates only on active shares (`updates-active-shares`)
A. The update call supplies share_id. The saved share record with that ID is read at call time and supplies its current status.
B. An update is refused when the saved status is anything other than active.
C. The update callback is not entered for a non-active share.

### Share update interval (`share-update-interval`)
A. The call supplies share_id and the app clock supplies current time. The latest successful share-update entry for that ID supplies the previous minute; age is whole minutes elapsed.
B. An update is refused when the age is less than two minutes. If no previous update is found or its time cannot be read, this interval rule does not fire.
C. The update callback is not entered when the interval is refused; other checks may still refuse a missing or unreadable record.

### Changed information on update (`changed-share-information`)
A. The call supplies share_id and optional ETA. Saved records supply the last successful create or update counter, the last ETA sent from the outbox, and the current stored ETA for the active or chosen trip.
B. Change is recorded when the app counter advanced since that share's last success, when the requested ETA differs from the last sent ETA, or when the trip's stored ETA differs from the last sent ETA. An update without such a change is refused.
C. The update callback is not entered when no change is recorded.

### No message after share ended (`no-message-after-share-ended`)
A. The message call supplies recipient, optional share_id, and an optional end-notice flag. Saved shares supply recipient and status, and the outbox supplies any earlier end notice for the same share. Only the app's stop flow supplies these special fields.
B. When the recipient has no active share but has a non-active share, a message is refused unless it is an end notice for that same non-active share and recipient and no earlier end notice exists for that share.
C. The ordinary message callback is not entered. The app's one-time end notice is sent through a separate permitted send function, and an ordinary model message cannot satisfy this special form.

### No trip details without active share (`no-trip-details-without-active-share`)
A. The message call supplies recipient and text. Saved shares determine whether that recipient has any active share, and the outbox supplies prior end notices.
B. When no active share exists for the recipient, a line or clock time in the message is refused unless the request is a valid one-time end notice.
C. The message callback is not entered when such a trip detail is present without an active share.

### Untrusted text forwarding (`untrusted-text-forwarding`)
A. The current outbound text or specialist request supplies the text. Stored alert and contact-reply text of at least 12 characters, plus stored extraction notes, supply passages to match exactly.
B. If any stored untrusted passage appears exactly in the text, the request is refused unless the tool is ask_user. Ask_user text is not inspected, so this exception is represented by a missing fact rather than a recorded exemption.
C. For instrumented share and specialist requests, the callback is not entered. An ask_user call is not refused by this rule and proceeds under ordinary ownership and turn permission.

### Contact data to specialists (`contact-data-specialists`)
A. The request text sent to Schedule, Transit, or Route is compared with contact IDs, names, channels, and addresses from saved contacts, plus existing share IDs. Only terms of at least three characters are compared.
B. A Schedule, Transit, or Route request containing any such contact term is refused. Share-agent requests are not covered by these rules.
C. The specialist request is not sent when contact material is detected.

### Saved places to Share agent (`saved-places-share-agent`)
A. The request text sent to the Share agent is matched against saved place names read from app data.
B. Any Share-agent request naming a saved place is refused; there is no exception for places on the current trip.
C. The specialist request is not sent when a saved place is named.

### Extraction output redaction (`extraction-output-redaction`)
A. The request supplies the Schedule agent identity and an image or text extraction tool. The successful tool result supplies the returned extraction object, while the app separately saves the full extraction.
B. A helper marks both Schedule extraction actions for redaction. It supports no permission decision and does not refuse either call.
C. After the original extraction returns a successful object, the installed post-call hook removes only the other_text key from the returned object. The saved extraction still contains it, other prose keys remain, and the extraction itself has already run.

## Limitations

- The duplicate agent-share rule uses an active channel-less share as a stand-in for user confirmation; no confirmation record, scope, or exact approval is produced. The app's original duplicate-share guard is a separate later check.
- The app turn and app-style share flags are not authenticated against the app. A create_share caller that supplies a nonempty channel can be treated as an app share, bypassing agent-share duplicate and ETA-share checks; trust, duration, content and precision rules still apply.
- No structured unfamiliar-recipient consent is recorded. Every create, message, or update to a recipient whose contact key lacks true trust is refused, and no approval path is implemented.
- Recipient trust matches only the lowercased contact key. A trusted contact's display name, address, or channel is not accepted as the recipient identity.
- The precision rule checks requested precision and distance, not the coordinate actually sent. Protected app shares pass on a rounding flag and rely on the original payload to round to two decimals; missing GPS produces no near-sensitive match.
- ETA checks match the rider's route ID but not the rider's departure against the stored compute_eta departure. Freshness is an internal counter for delays, alerts, and boarded trip only; time passing, chosen-trip changes, and failed compute_eta calls do not invalidate a prior successful row. An omitted eta_time is not compared.
- The changed-information rule uses delay, alert, boarding, or ETA changes as a proxy. It does not compare actual share fields or message text, so an unrelated event can make an empty update eligible while a message-only change is refused.
- The update interval reads the latest outbox share-update time. Absent or unreadable history leaves the interval rule silent; the first update is not made safe by this rule.
- Untrusted-text detection uses exact substring matching for stored alert, reply, or extraction text, and ask_user text is not instrumented. Paraphrased or reformatted untrusted text is not detected, and ask_user is not shown to have been checked.
- Extraction redaction removes only the other_text key from a successful returned object. The saved extraction retains any other_text returned by the extractor, other prose keys remain, and extraction has no permission refusal.
- No share-owner fact exists. Update and revocation gates check tool role, recipient trust, share status, or share ID, but not whether the actor or user owns that share; no revision or cancellation ownership check is implemented.
- Reading contacts and replies is restricted only by Share tool ownership. No rule distinguishes which contacts or replies may be read.
- Actor names are configured host-supplied names, not authenticated identities; the policy does not verify that the named agent made the call.
- Original application checks remain separate: channel-less create and update may run the original duplicate, field, and ETA guards when enabled; send_message may run its original field guard when enabled; app shares use the original share-sheet trust and duration prechecks and payload rounding. The added rules do not take credit for those checks.
- An allowed callback may return its own error, such as an unknown share, missing upload, or later original-guard rejection. Those are application errors, not refusals by this layer; unknown tools and malformed call inputs are also reported outside a policy decision.
- Rules read share status but do not change it; creation, revocation, arrival, and expiry are original application effects. The added layer only blocks a requested call.
- The app records a schedule confirmation state, but no added permission rule reads it. Extraction and later schedule use are not gated on that confirmation.
- An ask_user answer is an ordinary tool result. No rule records or consumes it as approval evidence for share creation or any other action.
- No approval, rejection, job-start, completion, or agent-declaration tool is installed. No requirement implements those categories, and no rule reads an agent statement.

## Unresolved Inputs

- A structured unfamiliar-recipient consent record, including who granted it and its scope.
- An exact user confirmation for a new agent share, its scope, expiry, and revocation evidence.
- Authenticated app-origin evidence for app-style share flags; currently a caller-supplied channel is the only signal.
- Share owner or creator identity and the authorized reader, updater, and revoker for each share ID.
- A binding of a stored compute_eta result to the rider's chosen departure, not only the route ID.
- The final rounded coordinates actually sent to recipients, if policy is meant to validate output instead of relying on payload rounding.
- A structured changed-field or changed-message observation for share updates.
- Text and related facts for ask_user calls, if untrusted-text checks are meant to cover them.
- An external delivery receipt or completion record for messages and end notices; only successful callback return and outbox append exist.
