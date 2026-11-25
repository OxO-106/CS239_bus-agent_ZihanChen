# Added enforcement

## Concierge requests to specialist agents

Records: When the Concierge sends a message to the schedule, transit, route or share agent, the gate sees the sender name, the action ask_<agent>_agent and the whole message text as the request. Contacts, rider distance and known share statuses are refreshed from the app just before the decision.

Rules: The request is allowed only when the sender is the Concierge and the action is one of the four specialist requests listed as Concierge capabilities. A refusal from the identifier check below overrides this. A refused message is not delivered and the specialist does not run; the Concierge gets a not-delivered notice.
Messages from any other sender are not gated. The Concierge's ask_user tool and the specialists' replies (including raw tool results passed back) are not checked.

## Bare contact or share identifiers kept from non-share specialists

Records: Uses the message text of a Concierge request to the schedule, transit or route agent, plus contact keys, names and channels refreshed from the app's contacts and get_contacts results, and share ids recorded when the share agent created a share.

Rules: An explicit Deny refuses the message when its entire text is exactly a contact key, a contact name, a contact channel or a recorded share id. Requests to the share agent are never refused by this check.
The match is whole-text equality only: a normal sentence that mentions a contact's name, phone channel or a share id is delivered. Ids of shares made in the app's share sheet are not recorded, and removed contacts keep their old records.

## Trusted recipient for share agent create_share

Records: Before the share agent's create_share runs, the gate reads the recipient argument and each contact's trusted flag and channel, refreshed from the app's contacts just before the decision. After a confirmed success it records the new share as active with its recipient, fields, precision, stop-on-arrival and protect-sensitive settings.

Rules: Allow requires the caller to be the share agent and the recipient to be either a trusted contact's key (such as mom) or the channel of a trusted contact. A display name, email or untrusted contact has no Allow, so the call is refused and no share is created.
The ETA condition below must also hold. Errors from the tool's own checks are passed through and nothing is recorded. The app's share sheet creates shares without this gate.

## ETA in a new share matches a computed ETA

Records: Reads the create_share eta flag and eta_time (empty when not given). Each successful compute_eta result returned to an agent is recorded as an ETA value when it returns and is kept for the whole session.

Rules: With eta on, eta_time must be non-empty and exactly equal one recorded compute_eta value; with eta off, eta_time must be empty. Otherwise there is no Allow and the share is refused.
Any ETA computed earlier in the session matches, even a stale one or one for a different route or trip.

## Shares must stop on arrival or last at most 240 minutes

Records: Reads the create_share duration in minutes (missing or 0 is treated as 0, meaning no expiry) and the stop-on-arrival flag from the call.

Rules: An explicit Deny refuses any share with a duration of more than 240 minutes, whether or not it stops on arrival. A second explicit Deny refuses a share with no duration and stop-on-arrival false. Both override any Allow.
A share of 1 to 240 minutes, or one with no duration that stops on arrival, is not refused by this check. Ending the share on arrival or at expiry is done by the app, not by the gate.

## Share-agent live location near a sensitive place

Records: Reads the create_share live-location flag, precision and protect-sensitive flag (default false, not offered to the agents; when true the app rounds the location near sensitive places). Just before the decision it records the rider's whole-meter distance from current GPS to the nearest place marked sensitive, such as Home.

Rules: For the share agent, an explicit Deny refuses a share with live location on, any precision other than neighborhood (exact or street), protect-sensitive false, and the rider within 300 meters of a sensitive place. Neighborhood precision passes.
The app's share sheet, where the user can turn off Hide where I live, is not covered by this refusal. A user's chat request to show the exact location is not recorded, so the agent path refuses it too. If GPS or sensitive places are missing, no new distance is recorded and an older one stays in use.

## update_share only on an active share

Records: Reads the update_share share id and message. Uses the share's lifecycle state, set to active after a share-agent create_share succeeds and moved to ended or expired when the app reports that the share ended on arrival or expired (checked just before each decision). After a successful update it records the update time and the sent ETA.

Rules: Allow requires the caller to be the share agent and the share to be in the active state with an active-to-active update move available. An unknown, app-made, revoked, ended or expired share gets an invalid-transition refusal.
The ETA condition below must also hold. The recorded update time is not used, so there is no limit on how often updates are sent.

## ETA in a share update matches a computed ETA

Records: Reads the update_share eta_time (empty when not given) and the compute_eta values recorded when that tool returned to an agent.

Rules: An empty eta_time is accepted. A non-empty eta_time must exactly equal one recorded compute_eta value; otherwise there is no Allow and the update is refused.
Any earlier computed ETA matches, regardless of share, route or age, and the share's own ETA setting is not checked.

## Share-agent updates to precise live-location shares near a sensitive place

Records: Uses the live-location flag, precision and protect-sensitive setting recorded when the share was created, and the rider's distance to the nearest sensitive place recorded just before the decision.

Rules: For the share agent, an explicit Deny refuses update_share when the share includes live location, its precision is not neighborhood, its protect-sensitive setting is false, and the rider is within 300 meters of a sensitive place.
This catches an exact share made away from Home whose rider later comes near Home. Updates made by the app itself are not covered.

## revoke_share only on an active share

Records: Reads the revoke_share share id and the share's lifecycle state. After a confirmed revoke the state moves to revoked and the share status is recorded as revoked.

Rules: Allow requires the caller to be the share agent and the share to be active with an active-to-revoked move available. Unknown, app-made, already revoked, ended or expired shares get an invalid-transition refusal.
The app's Stop button and Remove-all-data revoke without the gate.

## Messages only to trusted recipients with an active share

Records: Reads the send_message recipient and text. Uses the recipient recorded when a share-agent share was created, the share status recorded at creation and revoke and refreshed from the app before the decision, and contact trust records.

Rules: Allow requires the caller to be the share agent, some share whose recorded recipient is exactly this recipient with status active, and the recipient to be a trusted contact's key or a trusted contact's channel. Otherwise there is no Allow and the message is refused.
The message text is not checked by these rules. Shares from the app's share sheet are not recorded and cannot authorize a message; key and channel spellings must match the one used at creation.

## Final replies from Concierge and Route agent

Records: After the Concierge or the Route+ETA agent finishes a turn, including the app's own reply rewrites, the gate sees the final reply text and the agent name.

Rules: These replies are always allowed and no explicit Deny applies, so the reply is delivered unchanged. Other agents' replies are not gated.
The added rules place no restriction on what a reply to the student or the Concierge says.

## App share-sheet create_share (no gate)

Records: Nothing is recorded: the app's share sheet calls create_share directly, so no request from the app is ever made and no share records or lifecycle state are written.

Rules: The installed app permissions would mirror the share agent's trusted-recipient and ETA conditions, but they are never evaluated. The duration and sensitive-place refusals are not applied to share-sheet shares; only the sheet's own trusted-contact and duration choices apply.

## App update_share (no gate)

Records: Nothing is recorded: automatic ETA updates for app-made shares after boarding or delay events call update_share directly.

Rules: The installed app permissions would mirror the share agent's active-share and ETA conditions, but no app request reaches the gate, so these updates are unchecked.

## App revoke_share (no gate)

Records: Nothing is recorded by the gate: the Stop button and Remove-all-data call revoke_share directly. A revoked agent share's status is picked up only at the next refresh before another gated call, and its lifecycle stays active.

Rules: The installed app permission would require an active share, but no app request reaches the gate, so app revokes are unchecked.
