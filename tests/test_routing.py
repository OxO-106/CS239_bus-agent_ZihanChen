"""Route search on a tiny synthetic network, so every rule in plan.md §3 is checked in isolation.

Geography: origin at lat 34.000, destination at lat 34.050 (0.001 deg lat ~ 111 m ~ 1.8 min walk).
"""
from datetime import date

import pytest

from bus_agent.gtfs import Network, Stop, Trip
from bus_agent.routing import Router, clean_name, compare_options, parse_hhmm, plan_routes

TUESDAY = date(2026, 10, 27)
ORIGIN = (34.000, -118.400)
DEST = (34.050, -118.400)

STOPS = {
    "A1": 34.0005,   # next to origin
    "A2": 34.0004,
    "F": 33.9934,    # ~12 min walk from origin
    "M1": 34.0250,   # transfer point
    "M2": 34.0252,   # ~0.4 min from M1
    "M3": 34.0275,   # ~4.5 min from M1: too far to transfer
    "B8": 34.0496,
    "B9": 34.0495,   # next to destination
}


def trip(tid, line, stops, service="wk"):
    return Trip(tid, line, service, "0", "",
                [(s, parse_hhmm(t), parse_hhmm(t)) for s, t in stops])


@pytest.fixture
def router():
    net = Network()
    for sid, lat in STOPS.items():
        net.stops[sid] = Stop(sid, f"{sid} St / Main Ave", lat, -118.400)
    trips = [
        trip("x1", "X", [("A1", "08:00"), ("B9", "08:20")]),
        trip("x2", "X", [("A1", "08:20"), ("B9", "08:40")]),
        trip("x3", "X", [("A1", "08:40"), ("B9", "09:00")]),
        trip("s1", "SLOW", [("A1", "08:05"), ("B9", "08:45")]),
        trip("t1", "T1", [("A2", "08:00"), ("M1", "08:10")]),
        trip("t2", "T2", [("M2", "08:15"), ("B8", "08:30")]),
        trip("t3", "T3", [("M3", "08:15"), ("B8", "08:30")]),
        trip("f1", "FAR", [("F", "08:00"), ("B9", "08:25")]),
        trip("w1", "WKND", [("A1", "08:00"), ("B9", "08:20")], service="sat"),
    ]
    for t in trips:
        net.trips[t.id] = t
        net.lines[t.line] = "bus"
    net.calendar = {"wk": ("20260101", "20261231", {0, 1, 2, 3, 4}),
                    "sat": ("20260101", "20261231", {5})}
    net.index()
    return Router(net)


def ids(result):
    return {r["route_id"] for r in result["routes"]}


def by_line(result):
    return {"+".join(r["lines"]): r for r in result["routes"]}


def test_direct_route_has_stable_id(router):
    early = plan_routes(router, ORIGIN, DEST, TUESDAY, "07:30")
    later = plan_routes(router, ORIGIN, DEST, TUESDAY, "08:10")
    assert "X:A1St&MainAve>B9St&MainAve" in ids(early) & ids(later)


def test_slower_direct_line_is_listed_too(router):
    lines = by_line(plan_routes(router, ORIGIN, DEST, TUESDAY, "07:30"))
    assert {"X", "SLOW"} <= set(lines)
    assert "fastest" in lines["X"]["labels"] and "fastest" not in lines["SLOW"]["labels"]


def test_next_two_departures_and_leave_by(router):
    x = by_line(plan_routes(router, ORIGIN, DEST, TUESDAY, "07:30"))["X"]
    assert [d["depart"] for d in x["next_departures"]] == ["08:00", "08:20"]
    assert x["leave_by"] == "07:59"  # 1-min walk to A1
    assert x["next_departures"][0]["arrive"] == "08:21"  # door arrival includes the walk from B9


def test_transfer_within_three_minutes(router):
    lines = by_line(plan_routes(router, ORIGIN, DEST, TUESDAY, "07:30"))
    assert lines["T1+T2"]["transfers"] == 1
    assert "T1+T3" not in lines  # M1 -> M3 is a 4.5-min walk


def test_walk_limit_and_show_more(router):
    assert "FAR" not in by_line(plan_routes(router, ORIGIN, DEST, TUESDAY, "07:30"))
    more = by_line(plan_routes(router, ORIGIN, DEST, TUESDAY, "07:30", max_walk=15))
    assert "longer walk" in more["FAR"]["labels"]


def test_not_running_today_is_excluded_with_reason(router):
    result = plan_routes(router, ORIGIN, DEST, TUESDAY, "07:30")
    assert "WKND" not in by_line(result)
    assert {"route_id": "WKND:A1St&MainAve>B9St&MainAve", "reason": "not_running_today"} in result["excluded"]


def test_last_trip_passed(router):
    result = plan_routes(router, ORIGIN, DEST, TUESDAY, "09:00")
    assert {"route_id": "X:A1St&MainAve>B9St&MainAve", "reason": "last_trip_passed"} in result["excluded"]


def test_closed_stop_drops_route_with_reason(router):
    before = plan_routes(router, ORIGIN, DEST, TUESDAY, "07:30")
    after = plan_routes(router, ORIGIN, DEST, TUESDAY, "07:30", closed_stops={"A1": "alert-1"})
    assert "X" not in by_line(after)
    diff = {d["route_id"]: d for d in compare_options(before, after)}
    assert diff["X:A1St&MainAve>B9St&MainAve"] == {
        "route_id": "X:A1St&MainAve>B9St&MainAve", "status": "dropped", "reason": "stop_closed:alert-1"}


def test_compare_kept_changed_new(router):
    before = plan_routes(router, ORIGIN, DEST, TUESDAY, "07:30")
    after = plan_routes(router, ORIGIN, DEST, TUESDAY, "07:30", delays={"x1": 300}, max_walk=15)
    status = {d["route_id"].split(":")[0]: d["status"] for d in compare_options(before, after)}
    assert status["X"] == "changed"
    assert status["SLOW"] == "kept"
    assert status["FAR"] == "new"
    # no previous route disappears without a reason (SR17)
    assert all("reason" in d for d in compare_options(before, after) if d["status"] == "dropped")


def test_arrive_by_picks_latest_departures_in_time(router):
    x = by_line(plan_routes(router, ORIGIN, DEST, TUESDAY, "07:30", arrive_by="08:45"))["X"]
    # x1 (08:20) and x2 (08:40) arrive by 08:45, x3 (09:00) does not: latest first, leave as late as possible
    assert [d["depart"] for d in x["next_departures"]] == ["08:20", "08:00"]
    assert x["leave_by"] == "08:19" and "arrives late" not in x["labels"]
    no_deadline = by_line(plan_routes(router, ORIGIN, DEST, TUESDAY, "07:30"))["X"]
    assert [d["depart"] for d in no_deadline["next_departures"]] == ["08:00", "08:20"]


def test_arrives_late_still_listed(router):
    lines = by_line(plan_routes(router, ORIGIN, DEST, TUESDAY, "07:30", arrive_by="08:10"))
    assert "arrives late" in lines["X"]["labels"]


def test_services_on_calendar_exception(router):
    router.net.exceptions[("wk", "20261027")] = 2
    assert "wk" not in router.net.services_on(TUESDAY)
    result = plan_routes(router, ORIGIN, DEST, TUESDAY, "07:30")
    assert result["count"] == 0


def test_clean_name():
    assert clean_name("PICO EB & SEPULVEDA NS (Sepulveda Station)") == "Pico & Sepulveda"
    assert clean_name("Expo / Sepulveda Station") == "Expo & Sepulveda Station"


# ---------- which transfer counts are listed ----------

CHAIN_STOPS = {"C1": 34.0100, "C2": 34.0102, "C3": 34.0350, "C4": 34.0352}


def small_router(trips):
    """A network with the base stops plus a C1..C4 chain, and only the given trips."""
    net = Network()
    for sid, lat in {**STOPS, **CHAIN_STOPS}.items():
        net.stops[sid] = Stop(sid, f"{sid} St / Main Ave", lat, -118.400)
    for t in trips:
        net.trips[t.id] = t
        net.lines[t.line] = "bus"
    net.calendar = {"wk": ("20260101", "20261231", {0, 1, 2, 3, 4})}
    net.index()
    return Router(net)


DIRECTS = [trip(f"d{i}", f"D{i}", [("A1", f"08:0{i}"), ("B9", f"08:2{i}")]) for i in range(3)]
ONE_TRANSFER = [trip("t1", "T1", [("A2", "08:00"), ("M1", "08:10")]), trip("t2", "T2", [("M2", "08:15"), ("B8", "08:30")])]
TWO_TRANSFERS = [trip("p", "P", [("A1", "08:00"), ("C1", "08:05")]), trip("q", "Q", [("C2", "08:10"), ("C3", "08:20")]),
                 trip("r", "R", [("C4", "08:25"), ("B9", "08:35")])]


def test_enough_direct_routes_hide_transfers_with_reason():
    result = plan_routes(small_router(DIRECTS + ONE_TRANSFER), ORIGIN, DEST, TUESDAY, "07:30")
    assert {r["transfers"] for r in result["routes"]} == {0} and result["count"] == 3
    assert {"route_id": "T1:A2St&MainAve>M1St&MainAve|T2:M2St&MainAve>B8St&MainAve",
            "reason": "more_transfers_than_needed"} in result["excluded"]


def test_few_direct_routes_add_one_transfer():
    result = plan_routes(small_router(DIRECTS[:2] + ONE_TRANSFER + TWO_TRANSFERS), ORIGIN, DEST, TUESDAY, "07:30")
    assert sorted(r["transfers"] for r in result["routes"]) == [0, 0, 1]  # not two transfers


def test_only_transfer_routes_add_two_transfers():
    result = plan_routes(small_router(ONE_TRANSFER + TWO_TRANSFERS), ORIGIN, DEST, TUESDAY, "07:30")
    lines = by_line(result)
    assert set(lines) == {"T1+T2", "P+Q+R"}
    pqr = lines["P+Q+R"]
    assert pqr["transfers"] == 2 and pqr["next_departures"][0]["depart"] == "08:00"
    assert pqr["route_id"] == "P:A1St&MainAve>C1St&MainAve|Q:C2St&MainAve>C3St&MainAve|R:C4St&MainAve>B9St&MainAve"


def test_late_routes_do_not_count_toward_three():
    # three direct lines, but by 08:21 only D0 arrives (08:20 + 1 min walk); D1, D2 are late
    result = plan_routes(small_router(DIRECTS + ONE_TRANSFER), ORIGIN, DEST, TUESDAY, "07:30", arrive_by="08:21")
    assert 1 in {r["transfers"] for r in result["routes"]}


def test_line_not_running_for_hours_is_excluded_with_reason(router):
    early = plan_routes(router, ORIGIN, DEST, TUESDAY, "05:00")
    assert "X" not in by_line(early)
    assert {"X:A1St&MainAve>B9St&MainAve": "not_running_now"}.items() <= {e["route_id"]: e["reason"] for e in early["excluded"]}.items()
    assert "X" in by_line(plan_routes(router, ORIGIN, DEST, TUESDAY, "05:00", arrive_by="09:00"))
