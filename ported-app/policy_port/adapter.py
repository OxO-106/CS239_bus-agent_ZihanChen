"""Host adapter: binds bus-agent's existing boundaries to the frozen policy.

Four original entry points get one additive decorator each; their bodies are unchanged:

- ``Agent._call`` (tool dispatch): share tools are gated; read-only tools run unchanged and their
  results are published as observations.
- ``Bus.send`` (Concierge -> specialist message): the request is gated before delivery.
- ``Agent.run`` (model context): observes visible model output and ask_user answers.
- ``Guarded.run`` (final reply of the Concierge / Route+ETA agent): the reply is gated before delivery.

The adapter only projects arguments and observed values into facts. Every authorization condition
lives in rules.dl. One policy instance belongs to one application session (one ``Trace``).
"""
import functools
import inspect
import json
from contextlib import nullcontext
from contextvars import ContextVar

from policyweave.enforcement.telemetry import current_trace

from policy_port.binding import CALLS, CONTRACT, make_policy

GATED_TOOLS = ("create_share", "update_share", "revoke_share", "send_message")
REPLY_ACTIONS = {"concierge": "concierge_reply", "route": "route_agent_reply"}
PARTICIPANTS = {"concierge": "agent", "schedule": "agent", "transit": "agent", "route": "agent",
                "share": "agent", "user": "user", "world": "environment"}
SINGLE = {name for name, d in CONTRACT["fields"].items() if d["cardinality"] == "one"}

_WORLD = ContextVar("bus_agent_policy_world", default=None)


def _jsonable(value):
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _flag(value):
    return "true" if value else "false"


def _world_of(function, depth=2):
    """The app World captured by an original tool closure (tools are built as closures over ``w``)."""
    code, cells = getattr(function, "__code__", None), getattr(function, "__closure__", None) or ()
    if code is None:
        return None
    for name, cell in zip(code.co_freevars, cells):
        try:
            value = cell.cell_contents
        except ValueError:
            continue
        if name == "w":
            return value
        if depth and callable(value):
            found = _world_of(value, depth - 1)
            if found is not None:
                return found
    return None


class _Session:
    """Policy state for one app session, attached to its Trace object."""

    def __init__(self):
        self.world = None
        self.serial = 0
        self.block = None
        self.policy = make_policy(target="share_id", completed=self._completed,
                                  after=self._after, refusal=self._refusal)

    # ---------- result interpretation (the app's own success/failure shapes) ----------

    @staticmethod
    def _completed(value):
        return not (isinstance(value, dict) and "error" in value)

    def _refusal(self, action, feedback):
        codes = [c for c in feedback.get("reasonCodes", [])]
        why = (f"denied by rule {', '.join(codes)}" if feedback.get("reasonType") == "explicit_deny" and codes
               else "no rule permits this call with these arguments")
        text = f"Blocked by policy ({why}); the {action} call was not carried out."
        self.block = dict(action=action, requestId=feedback.get("requestId"), reasonType=feedback.get("reasonType"),
                          reasonCodes=codes, text=text)
        if action.startswith("ask_"):
            return f"(not delivered) {text}"
        if action.endswith("_reply"):
            return f"(reply withheld) {text}"
        return {"error": text}

    def take_block(self):
        block, self.block = self.block, None
        return block

    def next_id(self, prefix):
        self.serial += 1
        return f"{prefix}-{self.serial}"

    # ---------- observations ----------

    def _replace(self, facts, rows, obj, name, value):
        """Single-valued fields: drop the old value and insert the observed one in the same update."""
        value = str(value)
        if name in SINGLE:
            for row in rows:
                if row[0] == obj and row[1] == name and row[2] != value:
                    facts.delete("Field", *row)
        facts.put("Field", obj, name, value)

    def observe(self):
        """Refresh host observations of the current world before a gate (contacts, clock, GPS, share status)."""
        w = self.world
        if w is None:
            return

        def update(facts):
            rows = facts.rows("Field")
            for key, contact in (w.contacts or {}).items():
                self._replace(facts, rows, key, "contact_trusted", _flag(contact.get("trusted")))
                if contact.get("channel"):
                    self._replace(facts, rows, key, "contact_channel", contact["channel"])
                if contact.get("name"):
                    self._replace(facts, rows, key, "contact_name", contact["name"])
            self._replace(facts, rows, "world", "world_now_epoch_ms", int(w.now.timestamp() * 1000))
            distance = self._sensitive_distance(w)
            if distance is not None:
                self._replace(facts, rows, "rider", "rider_min_sensitive_distance_m", distance)
            known = {row[0] for row in rows if row[1] == "share_status"}
            states = {row[0]: row for row in facts.rows("ResourceState")}
            for share_id, share in (w.shares or {}).items():
                if share_id in known:
                    self._replace(facts, rows, share_id, "share_status", share["status"])
                    # The world ends a share on arrival (and the app on expiry) outside any gated call; the
                    # observed end moves the share's lifecycle state along the frozen arrive/expire edges.
                    state = states.get(share_id)
                    if state is not None and state[1] == "active" and share["status"] in ("ended", "expired"):
                        facts.put("ResourceState", share_id, share["status"])  # keyed by resource: replaces the row

        self.policy.update(update)

    @staticmethod
    def _sensitive_distance(w):
        from bus_agent.tools import meters

        gps = getattr(w, "gps", None) or {}
        places = [p for p in (w.places or {}).values() if p.get("sensitive")]
        if "lat" not in gps or not places:
            return None
        return int(min(meters(gps["lat"], gps["lon"], p["lat"], p["lon"]) for p in places))

    def produce(self, tool, result):
        """Publish read-only tool results the rules consume (host ingestion after the original returns)."""
        if not isinstance(result, dict) or "error" in result:
            return
        rows = []
        if tool == "get_contacts":
            for key, contact in (result.get("contacts") or {}).items():
                rows.append((key, "contact_trusted", _flag(contact.get("trusted"))))
                if contact.get("channel"):
                    rows.append((key, "contact_channel", contact["channel"]))
                if contact.get("name"):
                    rows.append((key, "contact_name", contact["name"]))
        elif tool == "compute_eta" and result.get("eta"):
            obj = self.next_id("eta")
            rows += [(obj, "eta_value", result["eta"]), (obj, "eta_route_id", result.get("route_id", "")),
                     (obj, "eta_depart", result.get("depart", ""))]
        elif tool == "plan_routes":
            obj = self.next_id("plan")
            routes = result.get("routes") or []
            rows.append((obj, "plan_count", len(routes)))
            rows += [(obj, "plan_route_id", r["route_id"]) for r in routes if r.get("route_id")]
        elif tool in ("extract_schedule_image", "extract_schedule_text"):
            rows.append((self.next_id("schedule"), "schedule_other_text_present",
                         _flag(str(result.get("other_text") or "").strip())))
        elif tool == "get_service_alerts":
            for alert in result.get("alerts") or []:
                for stop in alert.get("closed_stops") or []:
                    rows.append((str(alert.get("id")), "alert_closed_stop", stop))
        if rows:
            self.policy.update(lambda facts: [self._replace(facts, facts.rows("Field"), *row) for row in rows])

    def record_answers(self, answers):
        rows = [(self.next_id("ask_user"), "ask_user_answer", str(a)) for a in answers]
        if rows:
            self.policy.update(lambda facts: [facts.put("Field", *map(str, row)) for row in rows])

    def _after(self, context, value):
        """Confirmed share effects, published in the same staged batch as the gate."""
        request, policy = context["request"], self.policy
        action, params = request["event"], request["parameters"]

        def replace(obj, name, new):
            self._replace(policy, policy.rows("Field"), obj, name, new)

        if action == "create_share":
            sid = value["share_id"]
            policy.put("ResourceType", sid, "share")
            policy.put("ResourceState", sid, "active")
            fields = value.get("fields", {})
            for name, new in (("share_recipient", value["recipient"]),
                              ("share_field_live_location", _flag(fields.get("live_location"))),
                              ("share_field_route", _flag(fields.get("route"))),
                              ("share_field_eta", _flag(fields.get("eta"))),
                              ("share_precision", value.get("precision")),
                              ("share_place_names", _flag(value.get("place_names"))),
                              ("share_stop_on_arrival", _flag(value.get("stop_on_arrival"))),
                              ("share_status", value.get("status", "active")),
                              ("share_protect_sensitive",
                               _flag(value.get("protect_sensitive", params.get("protect_sensitive") == "true")))):
                replace(sid, name, new)
        elif action == "update_share":
            w = _WORLD.get()
            if w is not None:
                replace(params["share_id"], "share_updated_at_ms", int(w.now.timestamp() * 1000))
                sent = value.get("sent") or {}
                if sent.get("eta"):
                    replace(f"outbox-{len(w.outbox) - 1}", "outbox_eta", sent["eta"])
        elif action == "revoke_share":
            replace(params["share_id"], "share_status", value.get("status", "revoked"))
        return value


def _session(trace):
    session = getattr(trace, "_policyweave_session", None)
    if session is None:
        session = _Session()
        trace._policyweave_session = session
    return session


def _participants():
    observer = current_trace()
    if observer is not None:
        for name, kind in PARTICIPANTS.items():
            observer.participant(name, kind=kind)
    return observer


def _log_block(trace, tool, block):
    trace.log("guard", "guard", {"policy": "PolicyWeave", "tool": tool, "blocked": block["text"],
                                 "reasons": block["reasonCodes"], "request": block["requestId"]})


# ---------- argument projection (frozen call contract) ----------

def _encode(tool, function, args):
    """Project the actual call onto the frozen parameters, applying the original's own defaults and coercions.
    Returns None when the call cannot bind (the original then raises its own error before any effect)."""
    try:
        bound = inspect.signature(function).bind(**args)
    except TypeError:
        return None
    bound.apply_defaults()
    a = bound.arguments
    try:
        if tool == "create_share":
            return {"recipient": str(a["recipient"]), "live_location": bool(a["live_location"]),
                    "route": bool(a["route"]), "eta": bool(a["eta"]), "precision": str(a["precision"]),
                    # the original treats a missing/0 duration alike (no expiry); 0 encodes both
                    "duration_min": int(a["duration_min"]) if a["duration_min"] else 0,
                    "stop_on_arrival": bool(a["stop_on_arrival"]),
                    "message": "" if a["message"] is None else str(a["message"]),
                    "eta_time": "" if a["eta_time"] is None else str(a["eta_time"]),
                    "hide_places": a["hide_places"] not in (False, "false", "False", 0, None),
                    "protect_sensitive": bool(a["protect_sensitive"]),
                    "channel": str(a["channel"]) if a["channel"] else ""}
        if tool == "update_share":
            return {"share_id": str(a["share_id"]), "message": "" if a["message"] is None else str(a["message"]),
                    "eta_time": "" if a["eta_time"] is None else str(a["eta_time"])}
        if tool == "revoke_share":
            return {"share_id": str(a["share_id"])}
        if tool == "send_message":
            return {"recipient": str(a["recipient"]), "text": str(a["text"])}
    except (TypeError, ValueError):
        return None
    return None


# ---------- boundary decorators ----------

def _policy_tool_dispatch(function):
    """Agent._call(name, args): share tools are gated; other tools are observed producers."""

    @functools.wraps(function)
    def _policy_checked_call(self, name, args):
        original = function
        session = _session(self.trace)
        entry = self.tools.get(name)
        if entry is not None:
            session.world = _world_of(entry[1]) or session.world
        observer = _participants()
        operation = observer.operation(self.name, name, _jsonable(args)) if observer else nullcontext(None)
        with operation as outcome:
            params = _encode(name, entry[1], args) if entry is not None and name in GATED_TOOLS else None
            if params is not None:
                session.observe()
                token = _WORLD.set(session.world)
                try:
                    result = session.policy.call(self.name, name, params, lambda: original(self, name, args))
                finally:
                    _WORLD.reset(token)
                if (block := session.take_block()) is not None:
                    _log_block(self.trace, name, block)
            else:
                result = original(self, name, args)
                if entry is not None:
                    session.produce(name, result)
                if outcome is not None:
                    outcome["outcome"] = "not_applied" if isinstance(result, dict) and "error" in result else "applied"
            if outcome is not None:
                outcome["value"] = _jsonable(result)
        return result

    return _policy_checked_call


def _policy_message(function):
    """Bus.send(sender, recipient, text): the Concierge's request is gated before the specialist runs."""

    @functools.wraps(function)
    def _policy_checked_send(self, sender, recipient, text, images=None):
        original = function
        action = f"ask_{recipient}_agent"
        if sender != "concierge" or action not in CALLS:
            return original(self, sender, recipient, text, images)
        session = _session(self.trace)
        session.world = session.world or next(
            (a.world for a in self.agents.values() if getattr(a, "world", None) is not None), None)
        observer = _participants()

        def deliver():
            if observer is not None:
                observer.message(sender, [recipient], text, phase="sent")
            return True

        session.observe()
        verdict = session.policy.call(sender, action, {"request": str(text)}, deliver)
        if verdict is not True:
            block = session.take_block()
            if block is not None:
                _log_block(self.trace, action, block)
            if observer is not None:
                observer.message(sender, [recipient], text, phase="blocked")
            return verdict
        reply = original(self, sender, recipient, text, images)
        if observer is not None:
            observer.message(recipient, [sender], reply, phase="sent")
        return reply

    return _policy_checked_send


def _policy_model_context(function):
    """Agent.run: observes the visible model reply and the ask_user answers supplied into the context."""

    @functools.wraps(function)
    def _policy_observed_run(self, content, images=None):
        original = function
        reply = original(self, content, images)
        session = _session(self.trace)
        observer = _participants()
        if observer is not None:
            observer.model_output(self.name, reply, stage="reply")
        session.record_answers([r["answer"] for n, r in self.last_results
                                if n == "ask_user" and isinstance(r, dict) and "answer" in r])
        return reply

    return _policy_observed_run


def _policy_reply(function):
    """Guarded.run: the final reply (after the original reply guards) is gated before delivery."""

    @functools.wraps(function)
    def _policy_checked_reply(self, content, images=None):
        original = function
        session = _session(self.trace)
        session.world = getattr(self, "world", None) or session.world
        reply = original(self, content, images)
        action = REPLY_ACTIONS.get(self.name)
        if action is None:
            return reply
        session.observe()
        verdict = session.policy.call(self.name, action, {"reply_text": str(reply)}, lambda: reply)
        if (block := session.take_block()) is not None:
            _log_block(self.trace, action, block)
        return verdict

    return _policy_checked_reply
