"""Policy-boundary adapter for bus-agent's original tool dispatch.

The adapter observes the application's real World state, normalizes typed values,
and supplies EDB facts before an original tool callback runs. It never reimplements
a route planner, share sender, contact store, or authorization decision. Allow/Deny
and the substantive policy thresholds are in rules.dl and execute under native
Souffle through policyscope.enforcement.Policy.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from datetime import datetime
import json
import math
from pathlib import Path
import re

from policyscope.enforcement import Policy


PRECISION_DIGITS = {"exact": 5, "street": 3, "neighborhood": 2}
COORDINATE = re.compile(r"-?\d{2,3}\.\d{3,}\s*,\s*-?\d{2,3}\.\d{3,}")
CLOCK = re.compile(r"\b\d{1,2}:\d{2}\b")


def _json_snapshot(value):
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _truth(value):
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _policy_parameters(value):
    """Keep typed policy parameters while dropping optional None-valued call fields."""
    if isinstance(value, dict):
        nested = {}
        for name, item in value.items():
            clean = _policy_parameters(item)
            if clean is not _MISSING:
                nested[str(name)] = clean
        return nested if nested else _MISSING
    if value is None or not isinstance(value, (str, int, bool)):
        return _MISSING
    return value


def _hhmm(value):
    match = re.search(r"(\d{1,2}):(\d{2})", str(value))
    return f"{int(match.group(1)):02d}:{match.group(2)}" if match else str(value)


def _mentions(text, term):
    if not text or not term:
        return False
    return re.search(
        r"(?<![a-z0-9])" + re.escape(str(term).lower()) + r"(?![a-z0-9])",
        str(text).lower(),
    ) is not None


def _meters(lat1, lon1, lat2, lon2):
    """Great-circle distance in metres; independent of any policy threshold."""
    radius = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


TOOL_PRINCIPALS = {
    "ask_user": "concierge",
    "ask_schedule_agent": "concierge",
    "ask_transit_agent": "concierge",
    "ask_route_agent": "concierge",
    "ask_share_agent": "concierge",
    "extract_schedule_image": "schedule",
    "extract_schedule_text": "schedule",
    "lookup_building": "schedule",
    "get_classes": "schedule",
    "list_routes": "transit",
    "get_schedule": "transit",
    "get_realtime_arrivals": "transit",
    "get_service_alerts": "transit",
    "list_places": "route",
    "geocode": "route",
    "walk_time": "route",
    "plan_routes": "route",
    "compare_options": "route",
    "compute_eta": "route",
    "get_contacts": "share",
    "create_share": "share",
    "update_share": "share",
    "revoke_share": "share",
    "send_message": "share",
    "read_replies": "share",
}


_MISSING = object()


class PortAdapter:
    """Attach to original Agent objects as ``policy_port``.

    ``turn(principal, source)`` records the host's dispatch provenance. Sources are
    ``concierge`` for a hub request and ``app`` for the user's own share-sheet/stop
    operation. The capability rules still decide whether that turn is sufficient.
    """

    def __init__(self, world, *, rules_path=None, trace=True, _shared=None):
        self.world = world
        self.rules_path = Path(rules_path or Path(__file__).with_name("rules.dl"))
        self._turn_sources = ContextVar(
            f"bus_agent_port_turn_{id(self)}", default={}
        )
        self._shared = _shared or {
            "signature": None,
            "event_sequence": 0,
            "eta_rows": {},
            "share_update_seq": {},
            "adapters": [],
        }
        self._shared["adapters"].append(self)
        self._trace_enabled = bool(trace)
        self._request_sequence = {}
        self.policy = Policy(
            str(self.rules_path),
            trace=bool(trace),
            before=self._before,
            after=self._after,
            completed=lambda value: not (
                isinstance(value, dict) and value.get("error") is not None
            ),
            refused=lambda tool: {
                "error": f"policy denied {tool}",
                "policy": "denied",
            },
        )

    def for_agent(self, principal):
        """Return a runtime for one agent while sharing world-derived policy facts.

        The framework deliberately rejects re-entering the same policy session from
        a callback. Separate agent runtimes preserve that invariant when a Concierge
        message callback invokes a specialist's effect gate. World state and
        confirmed ETA observations remain shared by this adapter family.
        """
        if principal not in set(TOOL_PRINCIPALS.values()):
            raise ValueError(f"Unknown agent principal: {principal}")
        return PortAdapter(
            self.world,
            rules_path=self.rules_path,
            trace=self._trace_enabled,
            _shared=self._shared,
        )

    # ---- original entrypoint hook -------------------------------------------------
    def invoke(self, principal, tool, arguments, callback):
        """Run the original callback only after an explicit Datalog Allow.

        ``portTurn`` is adapter-owned provenance, not a model parameter. It is
        visible to policy Rules but is not passed to the original business function.
        """
        actual = deepcopy(dict(arguments))
        policy_arguments = {}
        for name, value in actual.items():
            clean = _policy_parameters(value)
            if clean is not _MISSING:
                policy_arguments[name] = clean
        source = self._turn_sources.get().get(principal)
        if source is None and principal == "concierge":
            source = "concierge"
        if source:
            policy_arguments["portTurn"] = source
        return self.policy.execute(
            principal,
            tool,
            policy_arguments,
            lambda _: callback(**actual),
        )

    @contextmanager
    def turn(self, principal, source):
        current = dict(self._turn_sources.get())
        previous = current.get(principal)
        current[principal] = source
        token = self._turn_sources.set(current)
        try:
            yield self
        finally:
            self._turn_sources.reset(token)
            if previous is None:
                current.pop(principal, None)
            else:
                current[principal] = previous

    def trajectory(self):
        return self.policy.trajectory()

    def trajectories(self):
        """Export every agent runtime in this adapter family as actual gate evidence."""
        return [adapter.policy.trajectory() for adapter in self._shared["adapters"]]

    # ---- pre-write fact production -----------------------------------------------
    def _before(self, context):
        request = context["request"]
        facts = context["facts"]
        q, action = request["id"], request["event"]
        parameters = dict(request.get("parameters") or {})

        self._sync_freshness(facts)
        self._sync_etas(facts)
        self._request_sequence[q] = self._shared["event_sequence"]
        self._sync_contacts(facts)
        self._sync_shares(facts)
        self._sync_trip(facts)
        self._request_facts(facts, q, action, parameters)

    def _sync_freshness(self, facts):
        signature = _json_snapshot(
            {
                "delays": dict(sorted(self.world.line_delays.items())),
                "alerts": list(self.world.alerts),
                "active_trip": self.world.active_trip,
            }
        )
        if signature != self._shared["signature"]:
            self._shared["event_sequence"] += 1
            self._shared["signature"] = signature
        facts.put("EventSeq", str(self._shared["event_sequence"]))

    def _sync_etas(self, facts):
        for row in self._shared["eta_rows"].values():
            facts.put("EtaForTrip", *row)

    def _sync_contacts(self, facts):
        for key, contact in self.world.contacts.items():
            facts.put(
                "RecipientTrusted",
                str(key).lower(),
                "true" if contact.get("trusted") else "false",
            )

    def _sync_shares(self, facts):
        state, agents, fields, place_names = [], [], [], []
        active_fields, active_place_names = set(), {}
        for share_id, share in self.world.shares.items():
            recipient = str(share.get("recipient", "")).strip().lower()
            channel = str(share.get("channel") or "")
            state.append(
                (str(share_id), recipient, str(share.get("status", "")), channel)
            )
            if not channel:
                agents.append((str(share_id),))
            for field, enabled in share.get("fields", {}).items():
                if enabled:
                    fields.append((str(share_id), str(field)))
            names = "true" if share.get("place_names", True) else "false"
            place_names.append((str(share_id), names))
            if share.get("status") == "active":
                for field, enabled in share.get("fields", {}).items():
                    if enabled:
                        active_fields.add((recipient, str(field)))
                active_place_names[recipient] = active_place_names.get(recipient, True) and (
                    share.get("place_names", True) is not False
                )

        for row in state:
            facts.put("ShareState", *row)
        self._replace(facts, "ShareAgent", agents, 1)
        self._replace(facts, "ShareField", fields, 2)
        self._replace(facts, "SharePlaceNames", place_names, 1)
        self._replace(facts, "RecipientActiveField", sorted(active_fields), 2)
        self._replace(
            facts,
            "RecipientActivePlaceNames",
            [
                (recipient, "true" if enabled else "false")
                for recipient, enabled in sorted(active_place_names.items())
            ],
            1,
        )
        for item in self.world.outbox:
            if item.get("end_notice") and item.get("share_id"):
                facts.put("ShareEndNotice", str(item["share_id"]))

    def _sync_trip(self, facts):
        trip = self.world.active_trip or self.world.chosen_trip
        old = facts.rows("RiderTrip")
        if trip:
            if old and old[0][0] != trip["route_id"]:
                for row in old:
                    facts.delete("RiderTrip", row[0])
            facts.put("RiderTrip", str(trip["route_id"]), str(trip["depart"]))
        else:
            for row in old:
                facts.delete("RiderTrip", row[0])

    @staticmethod
    def _replace(facts, name, rows, key_width):
        desired = [tuple(str(value) for value in row) for row in rows]
        wanted = {row[:key_width] for row in desired}
        for old in facts.rows(name):
            if old[:key_width] not in wanted:
                facts.delete(name, *old[:key_width])
        for row in desired:
            facts.put(name, *row)

    def _request_facts(self, facts, q, action, parameters):
        """Normalize one attempted call. No Allow/Deny branch lives here."""
        def flag(name, value):
            if value is not None:
                facts.put("AttemptFlag", q, name, str(value))

        def field(name):
            facts.put("AttemptField", q, name)

        share_id = parameters.get("share_id")
        share = self.world.shares.get(share_id) if share_id else None
        channel = parameters.get("channel")
        protect = _truth(parameters.get("protect_sensitive", False))
        if share_id:
            facts.put("AttemptShare", q, str(share_id))
        message = ""

        if action == "create_share":
            for name in ("live_location", "route", "eta"):
                if _truth(parameters.get(name, False)):
                    field(name)
            hide_places = parameters.get("hide_places", False)
            flag("place_names", "false" if _truth(hide_places) else "true")
            flag("stop_on_arrival", "true" if _truth(parameters.get("stop_on_arrival", True)) else "false")
            flag("agent_share", "false" if channel else "true")
            if channel:
                flag("exact_sensitive_choice", "false" if protect else "true")
                if protect:
                    flag("sensitive_rounding", "true")
            duration = parameters.get("duration_min", None)
            try:
                minutes = int(duration) if duration not in (None, "") else -1
            except (TypeError, ValueError):
                minutes = -2
            facts.put("AttemptDuration", q, str(minutes))
            facts.put(
                "AttemptPrecision",
                q,
                str(PRECISION_DIGITS.get(str(parameters.get("precision", "exact")), 5)),
            )
            recipient = str(parameters.get("recipient", "")).strip().lower()
            facts.put("AttemptRecipient", q, recipient)
            message = str(parameters.get("message", "") or "")
        elif action == "update_share":
            if share is not None:
                for name, enabled in share.get("fields", {}).items():
                    if enabled:
                        field(name)
                flag("place_names", "true" if share.get("place_names", True) else "false")
                channel = share.get("channel")
                protect = _truth(share.get("protect_sensitive", False))
                flag("agent_share", "false" if channel else "true")
                if channel:
                    flag("exact_sensitive_choice", "false" if protect else "true")
                    if protect:
                        flag("sensitive_rounding", "true")
                facts.put(
                    "AttemptPrecision",
                    q,
                    str(PRECISION_DIGITS.get(str(share.get("precision", "exact")), 5)),
                )
                flag(
                    "share_info_changed",
                    "true" if self._share_info_changed(share_id, share, parameters) else "false",
                )
                age = self._last_update_age(share_id)
                if age is not None:
                    facts.put("ShareUpdateAge", q, str(age))
            message = str(parameters.get("message", "") or "")
        elif action == "send_message":
            recipient = str(parameters.get("recipient", "")).strip().lower()
            facts.put("AttemptRecipient", q, recipient)
            active = any(
                str(s.get("recipient", "")).strip().lower() == recipient
                and s.get("status") == "active"
                for s in self.world.shares.values()
            )
            flag("no_active_share", "false" if active else "true")
            end_notice = _truth(parameters.get("end_notice", False))
            flag("agent_share", "false" if end_notice else "true")
            if end_notice:
                flag("end_notice", "true")
            message = str(parameters.get("text", "") or "")
        elif action in {"ask_schedule_agent", "ask_transit_agent", "ask_route_agent", "ask_share_agent"}:
            message = str(parameters.get("request", "") or "")

        if action in {"create_share", "update_share"}:
            eta_enabled = (
                _truth(parameters.get("eta", False))
                if action == "create_share"
                else bool(share and share.get("fields", {}).get("eta"))
            )
            if eta_enabled:
                flag("eta_field", "true")
                if not (self.world.active_trip or self.world.chosen_trip):
                    flag("no_rider_trip", "true")
            eta_time = parameters.get("eta_time")
            if eta_time not in (None, ""):
                facts.put("AttemptEtaTime", q, _hhmm(eta_time))
        if action in {"create_share", "update_share", "send_message", "ask_schedule_agent",
                     "ask_transit_agent", "ask_route_agent", "ask_share_agent"}:
            self._text_facts(facts, q, message)
            if action in {"create_share", "update_share"}:
                facts.put("SensitiveDistance", q, str(self._sensitive_distance()))

    def _last_update_age(self, share_id):
        updates = [
            str(item.get("at", ""))
            for item in self.world.outbox
            if item.get("kind") == "share_update" and item.get("share_id") == share_id
        ]
        if not updates:
            return None
        try:
            last = datetime.combine(self.world.now.date(), datetime.strptime(updates[-1], "%H:%M").time())
            return max(0, int((self.world.now - last).total_seconds() // 60))
        except (TypeError, ValueError):
            return None

    def _last_share_eta(self, share_id):
        for item in reversed(self.world.outbox):
            if str(item.get("share_id", "")) == str(share_id) and item.get("eta"):
                return _hhmm(item["eta"])
        return None

    def _share_info_changed(self, share_id, share, parameters):
        """Observe whether this update can carry newly changed shared information."""
        if share is None:
            return False
        last_sequence = int(self._shared["share_update_seq"].get(str(share_id), 0))
        if int(self._shared["event_sequence"]) > last_sequence:
            return True

        last_eta = self._last_share_eta(share_id)
        requested = parameters.get("eta_time")
        if requested not in (None, "") and _hhmm(requested) != last_eta:
            return True

        trip = self.world.active_trip or self.world.chosen_trip
        if trip and last_eta is not None:
            row = self._shared["eta_rows"].get(str(trip["route_id"]))
            if row and _hhmm(row[1]) != last_eta:
                return True
        return False

    def _sensitive_distance(self):
        gps = self.world.gps or {}
        if "lat" not in gps or "lon" not in gps:
            return 10**9
        values = [
            _meters(gps["lat"], gps["lon"], place["lat"], place["lon"])
            for place in self.world.places.values()
            if place.get("sensitive") and "lat" in place and "lon" in place
        ]
        return int(min(values)) if values else 10**9

    def _text_facts(self, facts, q, text):
        text = str(text or "")
        if not text:
            return
        routes = [
            route
            for plan in self.world.plans
            for route in plan.get("result", {}).get("routes", [])
        ]
        lines = {line for route in routes for line in route.get("lines", []) if line != "Walk"}
        planned_places = set()
        for plan in self.world.plans:
            planned_places.update(
                value for value in (plan.get("origin"), plan.get("destination")) if value
            )
        for route in routes:
            for leg in route.get("legs", []):
                planned_places.update(
                    value for value in (leg.get("board"), leg.get("alight")) if value
                )
        for line in sorted(lines):
            if _mentions(text, line):
                facts.put("MentionLine", q, line)
        for place in sorted(planned_places):
            if _mentions(text, place):
                facts.put("MentionPlace", q, place)
        time_values = sorted({_hhmm(value) for value in CLOCK.findall(text)})
        for value in time_values:
            facts.put("MessageTime", q, value)
        if COORDINATE.search(text):
            facts.put("MessageCoordinate", q)

        trip_places = set(planned_places)
        if self.world.plans:
            last = self.world.plans[-1]
            trip_places.update(
                value for value in (last.get("origin"), last.get("destination")) if value
            )
        for place in self.world.places:
            if _mentions(text, place):
                facts.put("AttemptMentionsSavedPlace", q, place)
                if place not in trip_places:
                    facts.put("AttemptOtherSavedPlace", q, place)

        classes = (self.world.schedule or {}).get("classes", [])
        course_hits = sum(_mentions(text, item.get("course", "")) for item in classes)
        schedule_texts = [
            str(value)
            for value in (
                (self.world.schedule or {}).get("other_text"),
                *[
                    upload.get("text")
                    for upload in getattr(self.world, "uploads", {}).values()
                ],
            )
            if value and len(str(value)) >= 16
        ]
        if course_hits >= 2 or any(value in text for value in schedule_texts):
            facts.put("AttemptMentionsSchedule", q, "true")

        contact_terms = []
        for key, contact in self.world.contacts.items():
            contact_terms.extend(
                [
                    str(key),
                    str(contact.get("name", "")),
                    str(contact.get("channel", "")),
                    str(contact.get("email", "")),
                ]
            )
        contact_terms.extend(str(share_id) for share_id in self.world.shares)
        if any(len(term) >= 3 and _mentions(text, term) for term in contact_terms if term):
            facts.put("AttemptMentionsContactData", q, "true")

        untrusted = [
            str(alert.get("text", ""))
            for alert in self.world.alerts
            if len(str(alert.get("text", ""))) >= 12
        ]
        untrusted.extend(
            str(reply.get("text", ""))
            for reply in self.world.replies
            if len(str(reply.get("text", ""))) >= 12
        )
        if (self.world.schedule or {}).get("other_text"):
            untrusted.append(str(self.world.schedule["other_text"]))
        if any(value in text for value in untrusted):
            facts.put("AttemptMentionsUntrusted", q, "true")

    # ---- confirmed-result fact production ---------------------------------------
    def _after(self, context, value):
        request = context["request"]
        q, action = request["id"], request["event"]
        facts = context["facts"]
        sequence = self._request_sequence.get(q, self._shared["event_sequence"])
        if action == "create_share" and isinstance(value, dict) and value.get("share_id"):
            self._shared["share_update_seq"][str(value["share_id"])] = str(sequence)
        if (
            action == "update_share"
            and isinstance(value, dict)
            and value.get("error") is None
            and request["parameters"].get("share_id")
        ):
            self._shared["share_update_seq"][str(request["parameters"]["share_id"])] = str(sequence)
        if (
            action == "compute_eta"
            and isinstance(value, dict)
            and value.get("error") is None
            and value.get("eta")
            and value.get("route_id")
        ):
            row = (
                str(value["route_id"]),
                str(value["eta"]),
                str(value.get("depart", "")),
                str(value.get("delay_min", 0)),
                str(sequence),
            )
            self._shared["eta_rows"][row[0]] = row
            facts.put("EtaForTrip", *row)
        if action in {"extract_schedule_image", "extract_schedule_text"}:
            redacted = any(
                row and row[0] == q for row in context["derived"].get("RedactOtherText", ())
            )
            if redacted and isinstance(value, dict) and "other_text" in value:
                value = {key: item for key, item in value.items() if key != "other_text"}
        return value

    # Policy.execute prepares facts before recording the request ID; capture this
    # request's pre-call freshness sequence when the rule program first sees it.


__all__ = ["PortAdapter"]
