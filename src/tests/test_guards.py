"""The P13 guard (on by default): shares and replies carry only the rider's own trip times."""
import pytest

from bus_agent import gtfs
from bus_agent.routing import Router
from bus_agent.agent import Agent
from bus_agent.agents import Concierge, p15_reply_check
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


def test_phase1_has_no_guard_and_no_depart(world):
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


def test_eta_only_message_naming_a_stop_is_blocked(world):
    world.guards = {"P5"}
    planned(world)
    result = call(share_tools(world), "create_share", recipient="mom", eta=True, message="Boarding at Sepulveda Blvd & Exposition Blvd.")
    assert "error" in result and "Sepulveda Blvd & Exposition Blvd" in result["error"]
