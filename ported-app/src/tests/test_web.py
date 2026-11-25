"""Web app: route geometry on the real feeds, and a scenario session with a stubbed model."""
import time

import pytest

from bus_agent import agent, gtfs
from bus_agent.routing import Router
from bus_agent.web import ROOT, App, Session, route_geometry

HOME, BOELTER = (34.0354, -118.4342), (34.0692, -118.4430)


@pytest.fixture(scope="module")
def router():
    return Router(gtfs.load())


def test_geometry_follows_shape(router):
    g = route_geometry(router, "CC6R:SepulvedaBlvd&ExpositionBlvd>UCLAGatewayPlaza", HOME, BOELTER,
                       gtfs.load_shapes(["ccb"]))
    kinds = [p["kind"] for p in g["parts"]]
    assert kinds == ["walk", "bus", "walk"]
    assert len(g["parts"][1]["coords"]) > 20  # street shape, not just the stops
    assert g["parts"][1]["board"] == "Sepulveda Blvd & Exposition Blvd"


def test_geometry_transfer_and_unknown(router):
    g = route_geometry(router, "E Line:Expo&Sepulveda>Westwood&RanchoPark|BBR12:Westwood&Exposition>WestwoodPlaza&Strathmore")
    assert [p["kind"] for p in g["parts"]] == ["rail", "walk", "bus"]
    assert route_geometry(router, "CC6R:Nowhere>Elsewhere") is None


def test_scenario_session_steps(router, monkeypatch):
    monkeypatch.setattr(agent, "chat", lambda *a, **k: {"message": {"role": "assistant", "content": "On it."}})
    items = []
    s = Session(router, ROOT / "scenarios/t3_share_with_mom.json", broadcast=items.append)
    assert s.state()["next"]["n"] == 1
    for _ in range(len(s.sc["events"])):
        assert s.step()
        while s.busy:
            time.sleep(0.01)
    replies = [i["event"]["data"]["text"] for i in items if i["type"] == "trace"
               and i["event"]["agent"] == "concierge" and i["event"]["data"]["to"] == "user"]
    assert replies == ["On it."] * 3  # the user message and two notices; boarding and GPS have none
    assert s.state()["next"] is None and s.state()["time"] == "09:20"
    assert not s.step()


def test_direct_planner_and_schedule_confirm(router):
    s = Session(router, ROOT / "scenarios/t3_share_with_mom.json")  # simulated Tuesday 08:20
    out = s.plan("Home", "Boelter Hall", "arrive", "10:00")
    assert out["ok"] and s.map["source"] == "planner" and s.map["found"] == out["count"] and not s.map["others"]
    assert s.map["query"] == {"origin": "Home", "destination": "Boelter Hall", "arrive_by": "10:00", "depart_after": None}
    assert "error" in s.plan("Nowhere", "Boelter Hall")
    s.schedule_confirm([{"course": "COM SCI 239", "days": ["Tu"], "start": "10:00", "end": "11:50",
                         "building": "Boelter Hall", "room": "5249"}])
    today = s.state()["today"]
    assert today["confirmed"] and today["classes"][0]["course"] == "COM SCI 239"
    assert today["classes"][0]["leave_by"]["time"] <= "10:00"  # from the plan just made
    actions = [e["data"]["action"] for e in s.trace.events if e["kind"] == "action"]
    assert actions == ["plan", "plan", "confirm_schedule"]


def test_share_sheet_lifecycle(router):
    """T3's world: plan, share ETA + location with Mom by text, board, delay, arrive; recipient view follows."""
    s = Session(router, ROOT / "scenarios/t3_share_with_mom.json")  # Tuesday 08:20, rider at the Home placeholder
    s.link_base = "http://localhost:8239"
    s.plan("Home", "Boelter Hall", "depart", "08:40")
    trip = next(r for r in s.world.plans[-1]["result"]["routes"] if r["lines"] == ["CC6R"])
    opts = {"recipient": "mom", "fields": {"eta": True, "live_location": True, "route": False}, "precision": "exact",
            "duration": "arrive", "channel": "text", "trip": {"route_id": trip["route_id"], "depart": "08:46"}}
    s.world.contacts["alex"] = {"name": "Alex", "trusted": False, "channel": "sms:+1-555-0102"}  # untrusted, test-only
    assert "error" in s.share({**opts, "recipient": "alex"})           # not a trusted contact
    out = s.share(opts)
    first = s.world.outbox[-1]
    assert first["channel"] == "text" and first["link"] == out["link"] and "Follow along" in first["message"]
    assert first["eta"] == "09:11" and first["location"] == {"lat": 34.04, "lon": -118.43}  # at Home: area only
    token = out["link"].rsplit("/", 1)[1]
    view = s.recipient_view(token)
    assert view["status"] == "active" and view["eta"] == "09:11" and view["location"]["radius_m"] == 800
    assert "lines" not in view                                          # route wasn't shared
    for event in s.sc["events"][1:]:                                    # board, gps, delay, arrive
        s.world.set_time(event["at"])
        s.world.apply(event)
        s._after_world_event(event)
    etas = [o["eta"] for o in s.world.outbox if o.get("eta")]
    assert etas == ["09:11", "09:19"]                                  # updated from compute_eta after the delay
    assert s.world.outbox[-1]["text"].startswith("Jamie arrived at Boelter Hall")
    ended = s.recipient_view(token)
    assert ended["status"] == "ended" and "location" not in ended and "eta" not in ended


def test_stop_share_and_link_share(router):
    s = Session(router, ROOT / "scenarios/t1_plan_my_day.json")  # Tuesday 08:00
    s.world.contacts["alex"] = {"name": "Alex", "trusted": False, "channel": "sms:+1-555-0102"}  # untrusted, test-only
    base = {"recipient": "mom", "fields": {"eta": False, "live_location": True, "route": False}, "precision": "area",
            "duration": "30", "trip": None}
    link = s.share({**base, "channel": "link"})
    text = s.share({**base, "channel": "text"})
    assert "error" in s.share({**base, "channel": "email", "recipient": "alex"})
    assert s.world.shares[link["share_id"]]["expires_at"].endswith("08:30:00")       # 30 min from 08:00
    sent = len(s.world.outbox)
    s.share_stop(link["share_id"])                                                    # a link has no one to notify
    assert len(s.world.outbox) == sent
    s.share_stop(text["share_id"])
    assert s.world.outbox[-1]["text"] == "Jamie stopped sharing their trip."
    assert s.recipient_view(text["link"].rsplit("/", 1)[1])["status"] == "revoked"
    preview = s.share_preview({**base, "channel": "email", "recipient": "mom",
                               "fields": {"eta": False, "live_location": True, "route": True}})
    assert "approximate area and bus" in preview["text"] and preview["subject"]


def test_hide_home_is_a_choice(router):
    s = Session(router, ROOT / "scenarios/t3_share_with_mom.json")  # rider at the Home placeholder
    opts = {"recipient": "mom", "fields": {"eta": False, "live_location": True, "route": False}, "precision": "exact",
            "duration": "arrive", "channel": "link", "trip": None}
    hidden = s.share(opts)
    shown = s.share({**opts, "hide_home": False})
    assert s.recipient_view(hidden["link"].rsplit("/", 1)[1])["location"]["radius_m"] == 800
    assert s.recipient_view(shown["link"].rsplit("/", 1)[1])["location"] == {"lat": 34.0354, "lon": -118.4342, "radius_m": 25}
    assert s.world.outbox[-1]["location"] == {"lat": 34.0354, "lon": -118.4342}


def test_place_names_are_a_choice(router):
    s = Session(router, ROOT / "scenarios/t3_share_with_mom.json")
    s.link_base = "http://localhost:8239"
    s.plan("Home", "Boelter Hall", "depart", "08:40")
    trip = next(r for r in s.world.plans[-1]["result"]["routes"] if r["lines"] == ["CC6R"])
    opts = {"recipient": "mom", "fields": {"eta": True, "live_location": False, "route": False}, "duration": "arrive",
            "channel": "text", "trip": {"route_id": trip["route_id"], "depart": "08:46"}}
    assert "Boelter Hall" in s.share_preview(opts)["text"]
    assert "Boelter Hall" not in s.share_preview({**opts, "place_names": False})["text"]
    named, hidden = s.share(opts), s.share({**opts, "place_names": False})
    assert "Boelter Hall" not in s.world.outbox[-1]["message"] and s.world.outbox[-1]["place_names"] is False
    assert s.recipient_view(named["link"].rsplit("/", 1)[1])["destination"] == "Boelter Hall"
    view = s.recipient_view(hidden["link"].rsplit("/", 1)[1])
    assert view["destination"] is None and "dest_point" not in view and view["eta"] == "09:11"


def test_remove_all_data(router, tmp_path):
    uploads, traces = tmp_path / "uploads", tmp_path / "traces"
    uploads.mkdir(), traces.mkdir()
    (uploads / "a.png").write_bytes(b"x")
    (traces / "live-web-20261027-120000.json").write_text("{}")
    (traces / "T1-run1-20261027-120000.json").write_text("{}")      # a CLI trace stays
    app = App(router)
    s = app.session
    out = s.share({"recipient": "mom", "fields": {"eta": False, "live_location": True, "route": False},
                   "precision": "area", "duration": "30", "channel": "text", "trip": None})
    res = app.remove_all_data(uploads, traces)
    assert res == {"ok": True, "shares_stopped": 1, "files_deleted": 2}
    assert s.world.shares[out["share_id"]]["status"] == "revoked"
    assert s.world.outbox[-1]["text"] == "Jamie stopped sharing their trip."
    assert [p.name for p in traces.iterdir()] == ["T1-run1-20261027-120000.json"] and not any(uploads.iterdir())
    assert app.session is not s and not app.session.world.shares and app.session.sc is None
