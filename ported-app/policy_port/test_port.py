"""Development tests for the policy port (deterministic, offline).

The LLM is an external service: every test replaces ``bus_agent.agent.chat`` with an explicitly labeled
OFFLINE MODEL FIXTURE that returns scripted replies and tool calls. These are not live student-agent runs.
The transit router is also external data: tests that need an ETA use a recorded walk-only plan fixture.
All tool callbacks, guards, the bus, the reply guards and the policy engine are the real ones.
"""
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

PROJECT = Path(__file__).resolve().parents[1]
for path in (PROJECT, PROJECT / "src"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from policyweave.enforcement import record_execution  # noqa: E402

from bus_agent.agents import build  # noqa: E402
from bus_agent.bus import Bus  # noqa: E402
from bus_agent.trace import Trace  # noqa: E402
from bus_agent.world import World  # noqa: E402

EVIDENCE = []


class OfflineModelFixture:
    """OFFLINE MODEL FIXTURE: scripted replies per agent instead of the Ollama model."""

    def __init__(self, **scripts):
        self.scripts = {agent: list(replies) for agent, replies in scripts.items()}

    def __call__(self, history, tools=None, agent=None, **kwargs):
        queue = self.scripts.get(agent) or []
        message = queue.pop(0) if queue else {"role": "assistant", "content": f"({agent} fixture: done)"}
        return {"message": message}


def tool_call(name, **arguments):
    return {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": name, "arguments": arguments}}]}


def say(text):
    return {"role": "assistant", "content": text}


def make_app(start="2026-11-24T08:40"):
    os.environ.pop("GUARDS", None)  # the app's default guards P4,P5,P13,P15
    trace = Trace({"scenario": "port-test"})
    world = World(None, start, trace)  # no router: tests never plan with the transit network
    trace.clock = lambda: world.hhmm
    bus = Bus(trace, lambda: world.hhmm)
    answers = []

    def ask_user(question):
        trace.log("concierge", "message", {"to": "user", "text": question})
        answer = answers.pop(0) if answers else "(no reply)"
        trace.log("user", "message", {"to": "concierge", "text": answer})
        return {"answer": answer}

    concierge = build(world, bus, trace, ask_user)
    return world, trace, bus, concierge, answers


def walk_plan(world, minutes=20):
    """Recorded plan_routes result fixture: one walk-only route from Home to Boelter Hall."""
    world.plans.append({"origin": "Home", "destination": "Boelter Hall", "points": ((0, 0), (0, 0)),
                        "arrive_by": None, "depart_after": None,
                        "result": {"routes": [{"route_id": "WALK", "lines": ["Walk"], "walk_min": {"from_stop": minutes},
                                               "leave_by": world.hhmm, "next_departures": []}]}})


def fields(trace):
    rows = []
    trace._policyweave_session.policy.update(lambda facts: rows.extend(facts.rows("Field")))
    return rows


def policy_blocks(trace):
    return [e["data"] for e in trace.events if e["kind"] == "guard" and e["data"].get("policy") == "PolicyWeave"]


class SharePortTests(unittest.TestCase):
    def setUp(self):
        self.world, self.trace, self.bus, self.concierge, self.answers = make_app()
        self.share, self.route = self.bus.agents["share"], self.bus.agents["route"]

    def tearDown(self):
        EVIDENCE.append({"test": self.id(), "outbox": self.world.outbox, "shares": list(self.world.shares.values()),
                         "policyBlocks": policy_blocks(self.trace)})

    def test_trusted_eta_share_with_computed_eta_is_applied(self):
        walk_plan(self.world)
        eta = self.route._call("compute_eta", {"route_id": "WALK", "depart": "08:40"})
        self.assertEqual(eta["eta"], "09:00")
        self.assertIn(("eta-1", "eta_value", "09:00"), fields(self.trace))
        result = self.share._call("create_share", {"recipient": "mom", "eta": True, "eta_time": "09:00"})
        self.assertEqual(result["share_id"], "s-001")
        self.assertEqual([o["kind"] for o in self.world.outbox], ["share_created"])
        self.assertEqual(self.world.outbox[0]["eta"], "09:00")
        self.assertIn(("s-001", "share_status", "active"), fields(self.trace))
        self.assertFalse(policy_blocks(self.trace))

    def test_eta_share_without_a_computed_eta_is_blocked(self):
        result = self.share._call("create_share", {"recipient": "mom", "eta": True, "eta_time": "09:00"})
        self.assertIn("Blocked by policy", result["error"])
        self.assertFalse(self.world.shares)
        self.assertFalse(self.world.outbox)
        self.assertEqual(policy_blocks(self.trace)[0]["tool"], "create_share")

    def test_untrusted_recipient_blocked_where_original_shares(self):
        # Original callback alone (no gate) on a separate world: the share is created.
        world, _, bus, _, _ = make_app()
        original = bus.agents["share"].tools["create_share"][1]
        self.assertEqual(original("+1-555-0199", live_location=True)["share_id"], "s-001")
        self.assertEqual(len(world.outbox), 1)
        # Protected entry point: blocked, nothing created or sent.
        result = self.share._call("create_share", {"recipient": "+1-555-0199", "route": True})
        self.assertIn("no rule permits", result["error"])
        self.assertFalse(self.world.shares)
        self.assertFalse(self.world.outbox)

    def test_share_over_240_minutes_or_without_end_is_denied(self):
        for args, reason in (({"duration_min": 300, "stop_on_arrival": False}, "p6_duration_over_240"),
                             ({"duration_min": 360}, "p6_duration_over_240"),  # stop_on_arrival defaults to true
                             ({"stop_on_arrival": False}, "p6_no_duration_or_stop")):
            result = self.share._call("create_share", {"recipient": "mom", "route": True, **args})
            self.assertIn(reason, result["error"])
        self.assertFalse(self.world.shares)
        self.assertFalse(self.world.outbox)
        ok = self.share._call("create_share", {"recipient": "mom", "route": True, "duration_min": 240,
                                               "stop_on_arrival": False})
        self.assertEqual(ok["share_id"], "s-001")

    def test_precise_live_location_near_home_is_denied(self):
        # The world starts with the rider at Home, a saved place marked sensitive.
        for precision in ("exact", "street"):
            result = self.share._call("create_share", {"recipient": "mom", "live_location": True,
                                                       "precision": precision})
            self.assertIn("p7_precise_near_sensitive", result["error"])
        self.assertFalse(self.world.outbox)
        ok = self.share._call("create_share", {"recipient": "mom", "live_location": True,
                                               "precision": "neighborhood"})
        self.assertEqual(ok["share_id"], "s-001")
        location = self.world.outbox[0]["location"]
        self.assertEqual(location["lat"], round(location["lat"], 2))

    def test_exact_share_made_away_from_home_cannot_update_near_home(self):
        self.world.apply({"type": "gps", "lat": 34.0689, "lon": -118.4452})  # on campus
        sid = self.share._call("create_share", {"recipient": "mom", "live_location": True})["share_id"]
        self.assertEqual(self.share._call("update_share", {"share_id": sid})["share_status"], "active")
        self.world.apply({"type": "gps", **{k: self.world.places["Home"][k] for k in ("lat", "lon")}})
        sent = len(self.world.outbox)
        result = self.share._call("update_share", {"share_id": sid})
        self.assertIn("p7_precise_near_sensitive_update", result["error"])
        self.assertEqual(len(self.world.outbox), sent)

    def test_share_ended_on_arrival_cannot_be_updated(self):
        sid = self.share._call("create_share", {"recipient": "mom", "route": True})["share_id"]
        self.world.apply({"type": "arrive", "place": "Boelter Hall"})
        self.assertEqual(self.world.shares[sid]["status"], "ended")
        sent = len(self.world.outbox)
        result = self.share._call("update_share", {"share_id": sid, "message": "Almost there"})
        self.assertIn("invalid_transition", result["error"])
        self.assertEqual(len(self.world.outbox), sent)
        self.assertIn("Blocked by policy", self.share._call("revoke_share", {"share_id": sid})["error"])
        self.assertIn("Blocked by policy", self.share._call("send_message", {"recipient": "mom", "text": "Here"})["error"])

    def test_share_lifecycle_update_then_revoke(self):
        sid = self.share._call("create_share", {"recipient": "mom", "route": True})["share_id"]
        update = self.share._call("update_share", {"share_id": sid, "message": "On my way"})
        self.assertEqual(update["share_status"], "active")
        revoked = self.share._call("revoke_share", {"share_id": sid})
        self.assertEqual(revoked["status"], "revoked")
        self.assertIn((sid, "share_status", "revoked"), fields(self.trace))
        before = len(self.world.outbox)
        again = self.share._call("update_share", {"share_id": sid, "message": "Still coming"})
        self.assertIn("Blocked by policy", again["error"])
        self.assertEqual(len(self.world.outbox), before)
        # The original callback alone would still send on the revoked share.
        original = self.share.tools["update_share"][1]
        self.assertIn("sent", original(sid, "Still coming"))

    def test_message_needs_an_active_share_to_the_recipient(self):
        blocked = self.share._call("send_message", {"recipient": "mom", "text": "Leaving now"})
        self.assertIn("Blocked by policy", blocked["error"])
        self.assertFalse(self.world.outbox)
        self.share._call("create_share", {"recipient": "mom", "route": True})
        sent = self.share._call("send_message", {"recipient": "mom", "text": "Leaving now"})
        self.assertEqual(sent["kind"], "message")

    def test_tool_errors_keep_the_original_shape(self):
        missing = self.share._call("create_share", {})
        self.assertTrue(missing["error"].startswith("TypeError"))
        unknown = self.share._call("no_such_tool", {})
        self.assertEqual(unknown, {"error": "unknown tool no_such_tool"})


class MessageAndReplyTests(unittest.TestCase):
    def setUp(self):
        self.world, self.trace, self.bus, self.concierge, self.answers = make_app()

    def test_specialist_request_is_gated_before_delivery(self):
        fixture = OfflineModelFixture(transit=[say("The next CC6R leaves at 08:46.")])
        with mock.patch("bus_agent.agent.chat", fixture):
            reply = self.bus.send("concierge", "transit", "When is the next CC6R at Sepulveda & Pico?")
            self.assertIn("08:46", reply)
            history = len(self.bus.agents["transit"].history)
            blocked = self.bus.send("concierge", "transit", "Mom")  # a contact's name sent to a non-Share agent
        self.assertIn("p19_contact_name", blocked)
        self.assertEqual(len(self.bus.agents["transit"].history), history)
        with self.assertRaises(ValueError):  # the original hub rule is preserved
            self.bus.send("transit", "share", "hello")

    def test_replies_are_gated_and_ask_user_answers_observed(self):
        fixture = OfflineModelFixture(concierge=[tool_call("ask_user", question="Share your ETA with Mom?"),
                                                 say("Okay, I won't share anything.")],
                                      route=[say("I need an origin and destination.")])
        self.answers.append("No thanks")
        with mock.patch("bus_agent.agent.chat", fixture):
            reply = self.concierge.run("[08:40] Hi")
            route_reply = self.bus.agents["route"].run("[08:40] plan something")
        self.assertEqual(reply, "Okay, I won't share anything.")
        self.assertEqual(route_reply, "I need an origin and destination.")
        self.assertIn(("ask_user-1", "ask_user_answer", "No thanks"), fields(self.trace))
        self.assertFalse(policy_blocks(self.trace))


class RecordedScenarioTest(unittest.TestCase):
    def test_share_request_scenario_is_recorded(self):
        world, trace, bus, concierge, _ = make_app()
        walk_plan(world)
        fixture = OfflineModelFixture(
            concierge=[tool_call("ask_route_agent", request="compute_eta for route WALK, depart 08:40"),
                       tool_call("ask_share_agent", request="Fields: eta only. Share the ETA 09:00 with mom."),
                       say("Mom now gets your ETA, 09:00.")],
            route=[tool_call("compute_eta", route_id="WALK", depart="08:40"), say("ETA 09:00.")],
            share=[tool_call("get_contacts"),
                   tool_call("create_share", recipient="mom", eta=True, eta_time="09:00"),
                   tool_call("send_message", recipient="+1-555-0199", text="Hi"),
                   say("Created share s-001 for mom.")])
        with record_execution("offline share scenario") as recording, mock.patch("bus_agent.agent.chat", fixture):
            reply = concierge.run("[08:40] Share my ETA with Mom")
        timeline = recording.export()
        events = timeline["events"]
        calls = [e for e in events if e["kind"] == "tool_call"]
        self.assertIn({"recipient": "mom", "eta": True, "eta_time": "09:00"},
                      [e["arguments"] for e in calls if e.get("tool") == "create_share"])
        results = {e["callId"]: e for e in events if e["kind"] == "tool_result"}
        create = next(e for e in calls if e.get("tool") == "create_share")
        self.assertEqual(results[create["callId"]]["result"]["share_id"], "s-001")
        blocked = next(e for e in calls if e.get("tool") == "send_message")
        self.assertIn("Blocked by policy", results[blocked["callId"]]["result"]["error"])
        messages = [(e["actor"], e["recipients"]) for e in events if e["kind"] == "message"]
        self.assertIn(("concierge", ["share"]), messages)
        self.assertIn(("share", ["concierge"]), messages)
        outputs = [e["result"] for e in events if e["kind"] == "llm_output" and e["actor"] == "concierge"]
        self.assertIn("Mom now gets your ETA, 09:00.", outputs)
        self.assertEqual(reply, "Mom now gets your ETA, 09:00.")
        self.assertEqual([o["kind"] for o in world.outbox], ["share_created"])
        EVIDENCE.append({"test": self.id(), "label": "OFFLINE MODEL FIXTURE (not a live model run)",
                         "timeline": timeline})


def tearDownModule():
    out = Path(__file__).with_name("trajectories.json")
    try:
        out.write_text(json.dumps(EVIDENCE, ensure_ascii=False, default=str)[:1_900_000])
    except OSError:
        pass


if __name__ == "__main__":
    unittest.main()
