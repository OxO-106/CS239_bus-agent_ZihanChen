"""The P13 guard (on by default): shares and replies carry only the rider's own trip times."""
import pytest

from bus_agent import gtfs
from bus_agent.routing import Router
from bus_agent.agent import Agent
from bus_agent.agents import Concierge, RouteAgent, p13_route_reply_check, p15_reply_check
from bus_agent.tools import p13_reply_check, route_tools, share_tools
from bus_agent.trace import Trace
from bus_agent.world import World

pytestmark = pytest.mark.skipif(not (gtfs.GTFS_DIR / "ccb" / "trips.txt").exists(), reason="trimmed GTFS missing")
CC6R = "CC6R:SepulvedaBlvd&ExpositionBlvd>UCLAGatewayPlaza"


@pytest.fixture(scope="module")
def router():
    return Router(gtfs.load())


@pytest.fixture
def world(router):
    trace = Trace({"scenario": "test"})
    w = World(router, "2026-10-27T08:20", trace)
    trace.clock = lambda: w.hhmm
    w.guards = {"P13"}
    return w


def call(tools, name, **args):
    return tools[name][1](**args)


def blocked(world):
    return [e["data"] for e in world.trace.events if e["kind"] == "guard"]


def planned(world):
    route = route_tools(world)
    call(route, "plan_routes", origin="Home", destination="Boelter Hall")
    return route


def test_guards_off_has_no_depart_and_no_eta_check(world):
    world.guards = set()
    schema = route_tools(world)["compute_eta"][0]["function"]["parameters"]["properties"]
    assert "depart" not in schema
    call(share_tools(world), "create_share", recipient="mom", eta=True, eta_time="08:53")
    assert world.outbox[-1]["eta"] == "08:53"


def test_compute_eta_for_the_chosen_departure_before_boarding(world):
    route = planned(world)
    assert "depart" in route["compute_eta"][0]["function"]["parameters"]["properties"]
    nxt = call(route, "compute_eta", route_id=CC6R)
    chosen = call(route, "compute_eta", route_id=CC6R, depart="08:46")
    assert chosen["depart"] == "08:46" and nxt["depart"] != "08:46"
    assert world.chosen_trip == {"route_id": CC6R, "depart": "08:46"}


def test_eta_for_another_bus_is_blocked(world):
    route = planned(world)
    nxt = call(route, "compute_eta", route_id=CC6R)["eta"]  # the next bus, not the rider's
    right = call(route, "compute_eta", route_id=CC6R, depart="08:46")["eta"]
    result = call(share_tools(world), "create_share", recipient="mom", eta=True, eta_time=nxt)
    assert "error" in result and right in result["error"] and not world.outbox
    assert blocked(world)[0]["policy"] == "P13"
    ok = call(share_tools(world), "create_share", recipient="mom", eta=True, eta_time=right)
    assert ok["status"] == "active" and world.outbox[-1]["eta"] == right


def test_missing_eta_is_filled_from_the_riders_trip(world):
    route = planned(world)
    right = call(route, "compute_eta", route_id=CC6R, depart="08:46")["eta"]
    call(share_tools(world), "create_share", recipient="mom", eta=True)
    assert world.outbox[-1]["eta"] == right


def test_no_riders_trip_is_blocked(world):
    planned(world)
    result = call(share_tools(world), "create_share", recipient="mom", eta=True, eta_time="09:11")
    assert "error" in result and "depart" in result["error"] and not world.outbox


def test_update_after_delay_must_follow_the_boarded_bus(world):
    route, share_t = planned(world), share_tools(world)
    call(route, "compute_eta", route_id=CC6R, depart="08:46")
    share = call(share_t, "create_share", recipient="mom", eta=True)
    world.set_time("08:46")
    world.apply({"type": "board", "route_id": CC6R, "depart": "08:46"})
    world.set_time("08:55")
    world.apply({"type": "delay", "line": "CC6R", "minutes": 8})
    right = call(route, "compute_eta", route_id=CC6R)["eta"]
    wrong = call(share_t, "update_share", share_id=share["share_id"], eta_time="09:32")
    assert "error" in wrong and right in wrong["error"]
    in_text = call(share_t, "update_share", share_id=share["share_id"], message="Now arriving 9:32.")
    assert "error" in in_text
    ok = call(share_t, "update_share", share_id=share["share_id"], message=f"Running late, now {right}.")
    assert ok["sent"]["eta"] == right and len(world.outbox) == 2


def test_app_share_sheet_is_not_affected(world):
    call(share_tools(world), "create_share", recipient="mom", eta=True, eta_time="09:11", channel="text",
         trip={"route_id": CC6R, "depart": "08:46"})
    assert world.outbox[-1]["eta"] == "09:11"


def boarded_and_delayed(world):
    route = planned(world)
    world.set_time("08:46")
    world.apply({"type": "board", "route_id": CC6R, "depart": "08:46"})
    world.set_time("08:55")
    world.apply({"type": "delay", "line": "CC6R", "minutes": 8})
    return call(route, "compute_eta", route_id=CC6R)


def test_reply_naming_another_bus_time_is_flagged(world):
    eta = boarded_and_delayed(world)
    error, fallback = p13_reply_check(world, f"The bus now departs at 09:03, so your ETA is {eta['eta']}.")
    assert "09:03" in error and eta["eta"] in fallback
    assert p13_reply_check(world, f"Your 08:46 bus is {eta['delay_min']} min late; new ETA {eta['eta']}.") is None


def test_reply_check_applies_only_with_a_riders_trip(world):
    planned(world)
    assert p13_reply_check(world, "Buses leave at 08:28 and 08:46.") is None


class Scripted(Concierge):
    """The guarded Concierge with the model replaced by a list of replies."""

    def __init__(self, world, replies):
        super().__init__(world, "concierge", "", {}, world.trace)
        self.replies, self.prompts = list(replies), []


def scripted(world, replies, monkeypatch):
    agent = Scripted(world, replies)
    monkeypatch.setattr(Agent, "run", lambda self, content, images=None: (self.prompts.append(content), self.replies.pop(0))[1])
    return agent


def test_concierge_rewrites_a_blocked_reply(world, monkeypatch):
    eta = boarded_and_delayed(world)["eta"]
    agent = scripted(world, ["Departs 09:03.", f"New ETA {eta}."], monkeypatch)
    assert agent.run("notice") == f"New ETA {eta}."
    assert "09:03" in agent.prompts[1] and len(blocked(world)) == 1


def test_concierge_falls_back_after_failed_rewrites(world, monkeypatch):
    eta = boarded_and_delayed(world)["eta"]
    agent = scripted(world, ["Departs 09:03."] * 3, monkeypatch)
    assert agent.run("notice").endswith(f"at {eta}.")
    assert blocked(world)[-1]["sent_instead"].endswith(f"at {eta}.")


def test_concierge_without_guards_is_unchanged(world, monkeypatch):
    boarded_and_delayed(world)
    world.guards = set()
    agent = scripted(world, ["Departs 09:03."], monkeypatch)
    assert agent.run("notice") == "Departs 09:03." and not blocked(world)


def plan_result(n=3):
    routes = [{"route_id": f"r{i}", "lines": [line]} for i, line in enumerate(["CC6R", "M761", "CC6"][:n])]
    return {"origin": "Home", "destination": "Boelter Hall", "count": n, "routes": routes}


def p15_turn(world):
    world.guards = {"P15"}
    world.trace.log("user", "message", {"to": "concierge", "text": "How do I get to Boelter Hall?"})


def test_reply_hiding_routes_is_flagged(world):
    turn = [{"t": "08:20", "agent": "route", "kind": "tool_result", "data": {"name": "plan_routes", "result": plan_result()}}]
    error, fallback = p15_reply_check(turn, "Take the CC6R.")
    assert "3 routes" in error and "CC6R, M761, CC6" in error and "There are 3 suitable routes" in fallback
    assert p15_reply_check(turn, "Take the CC6R, the M761 or the CC6.") is None
    assert p15_reply_check(turn, "There are 3 routes; the CC6R is fastest.") is None


def test_concierge_rewrites_a_reply_that_hides_routes(world, monkeypatch):
    p15_turn(world)
    agent = Scripted(world, ["Take the CC6R.", "Take the CC6R, the M761 or the CC6."])

    def run(self, content, images=None):  # the model plans on its first call, then only answers
        if not self.prompts:
            self.trace.log("route", "tool_result", {"name": "plan_routes", "result": plan_result()})
        self.prompts.append(content)
        return self.replies.pop(0)
    monkeypatch.setattr(Agent, "run", run)
    assert agent.run("How do I get to Boelter Hall?") == "Take the CC6R, the M761 or the CC6."
    assert "P15" in agent.prompts[1] and blocked(world)[0]["policy"] == "P15"


def test_concierge_appends_the_count_after_failed_rewrites(world, monkeypatch):
    p15_turn(world)
    agent = Scripted(world, ["Take the CC6R."] * 3)

    def run(self, content, images=None):
        if not self.prompts:
            self.trace.log("route", "tool_result", {"name": "plan_routes", "result": plan_result()})
        self.prompts.append(content)
        return self.replies.pop(0)
    monkeypatch.setattr(Agent, "run", run)
    assert agent.run("How do I get there?").endswith("There are 3 suitable routes from Home to Boelter Hall; ask me to show all of them.")


def test_share_message_naming_the_line_is_blocked(world):
    world.guards = {"P5"}
    planned(world)
    share_t = share_tools(world)
    result = call(share_t, "create_share", recipient="mom", eta=True, eta_time="09:11", message="On the Rapid 6.")
    assert "error" in result and "CC6R" in result["error"] and not world.outbox
    assert blocked(world)[0]["policy"] == "P5"
    call(share_t, "create_share", recipient="mom", eta=True, route=True, eta_time="09:11", message="On the Rapid 6.")
    assert world.outbox[-1]["message"] == "On the Rapid 6."


def test_place_names_are_allowed_by_default(world):
    world.guards = {"P5"}
    planned(world)
    call(share_tools(world), "create_share", recipient="mom", eta=True,
         message="On my way to Boelter Hall, boarding at Sepulveda Blvd & Exposition Blvd.")
    assert world.outbox[-1]["place_names"] is True and not blocked(world)


def test_place_names_off_blocks_stops_and_destination(world):
    world.guards = {"P5"}
    planned(world)
    share_t = share_tools(world)
    for message, named in (("Boarding at Sepulveda Blvd & Exposition Blvd.", "Sepulveda Blvd & Exposition Blvd"),
                           ("On my way to Boelter Hall.", "Boelter Hall")):
        result = call(share_t, "create_share", recipient="mom", eta=True, hide_places=True, message=message)
        assert "error" in result and named in result["error"] and "place names are off" in result["error"]
    assert not world.outbox
    call(share_t, "create_share", recipient="mom", eta=True, hide_places=True, message="On my way.")
    assert world.outbox[-1]["place_names"] is False
    assert "error" in call(share_t, "update_share", share_id="s-001", message="Almost at Boelter Hall.")


def plan_turn(world):
    """A Route+ETA turn: the trace events of one plan_routes call (Home -> Boelter Hall at 08:20)."""
    result = call(route_tools(world), "plan_routes", origin="Home", destination="Boelter Hall")
    world.trace.log("route", "tool_result", {"name": "plan_routes", "result": result})
    return [e for e in world.trace.events if e["kind"] == "tool_result"]


def test_route_reply_with_another_routes_times_is_flagged(world):
    turn = plan_turn(world)
    plan = turn[-1]["data"]["result"]
    m761 = next(r for r in plan["routes"] if r["lines"] == ["M761"])
    cc6r = next(r for r in plan["routes"] if r["lines"] == ["CC6R"])
    d = cc6r["next_departures"][0]
    wrong = f"There are {plan['count']} routes:\n* **M761**: next departure {d['depart']} (arrives {d['arrive']})"
    error, fallback = p13_route_reply_check(turn, wrong)
    assert d["depart"] in error and "M761" in error and plan["summary"][0] in fallback
    m = m761["next_departures"][0]
    right = f"* **M761**:\n    * Departs {m['depart']}, arrives {m['arrive']}, leave by {m761['leave_by']}"
    assert p13_route_reply_check(turn, right) is None
    assert p13_route_reply_check(turn, "\n".join(f"- {x}" for x in plan["summary"])) is None


def test_route_agent_rewrites_and_keeps_its_tool_results(world, monkeypatch):
    agent = RouteAgent(world, "route", "", {}, world.trace)
    replies = ["M761 leaves at 23:59.", "Copied the summary."]

    def run(self, content, images=None):
        self.last_results = []
        if len(replies) == 2:
            self.last_results = [("plan_routes", plan_turn(world)[-1]["data"]["result"])]
        return replies.pop(0)
    monkeypatch.setattr(Agent, "run", run)
    assert agent.run("Plan Home to Boelter Hall") == "Copied the summary."
    assert blocked(world)[0]["policy"] == "P13" and blocked(world)[0]["tool"] == "reply to the Concierge"
    assert [name for name, _ in agent.last_results] == ["plan_routes"]  # the hub still passes the plan on


def test_plain_message_says_no_more_than_the_recipients_shares(world):
    world.guards = {"P5"}
    planned(world)
    share_t = share_tools(world)
    result = call(share_t, "send_message", recipient="mom", text="I'm on the Rapid 6.")
    assert "error" in result and "CC6R" in result["error"] and not world.outbox
    call(share_t, "create_share", recipient="mom", route=True, message="Sharing my route.")
    call(share_t, "send_message", recipient="mom", text="I'm on the Rapid 6.")
    assert world.outbox[-1]["text"] == "I'm on the Rapid 6."


def test_route_reply_with_a_walk_trip_and_bold_titles_is_not_flagged(world):
    turn = plan_turn(world)
    walk = call(route_tools(world), "plan_routes", origin="Boelter Hall", destination="Knudsen Hall", depart_after="11:50")
    world.trace.log("route", "tool_result", {"name": "plan_routes", "result": walk})
    turn = [e for e in world.trace.events if e["kind"] == "tool_result"]
    bus = turn[0]["data"]["result"]
    reply = "\n".join([f"**1. Home to Boelter Hall**", f"There are {bus['count']} routes:",
                       *(f"* {x}" for x in bus["summary"]), "", "**2. Boelter Hall to Knudsen Hall (leaving after 11:50)**",
                       "There is 1 route:", *(f"* {x}" for x in walk["summary"])])
    assert p13_route_reply_check(turn, reply) is None


def test_route_reply_may_name_the_riders_scheduled_departure(world):
    planned(world)
    world.apply({"type": "board", "route_id": CC6R, "depart": "08:46"})
    world.apply({"type": "delay", "line": "CC6R", "minutes": 8})
    turn = plan_turn(world)
    for depart in ("08:46", "09:03"):  # the rider's bus, then a departure the Concierge got wrong
        eta = call(route_tools(world), "compute_eta", route_id=CC6R, depart=depart)
        assert eta["trip_depart"] == "08:46"
        world.trace.log("route", "tool_result", {"name": "compute_eta", "result": eta})
    turn = [e for e in world.trace.events if e["kind"] == "tool_result"]
    reply = f"For the Rapid 6 (CC6R) trip originally departing at 08:46, the new ETA is {eta['eta']}."
    assert p13_route_reply_check(turn, reply) is None
    assert p13_route_reply_check(turn, reply.replace("08:46", "09:03")) is not None


def test_second_share_to_the_same_recipient_is_blocked(world):
    world.guards = {"P4"}
    share_t = share_tools(world)
    first = call(share_t, "create_share", recipient="mom", eta=True, eta_time="09:11")
    result = call(share_t, "create_share", recipient="Mom", eta=True, eta_time="09:11")
    assert "error" in result and first["share_id"] in result["error"] and len(world.shares) == 1
    assert blocked(world)[0]["policy"] == "P4"
    assert "error" not in call(share_t, "create_share", recipient="sam", eta=True, eta_time="09:11")
    call(share_t, "revoke_share", share_id=first["share_id"])
    assert "error" not in call(share_t, "create_share", recipient="mom", eta=True, eta_time="09:11")
    app = call(share_t, "create_share", recipient="mom", eta=True, eta_time="09:11", channel="text", link_base="")
    assert "error" not in app  # the share sheet is the user's own explicit choice
