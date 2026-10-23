"""Web app: route geometry on the real feeds, and a scenario session with a stubbed model."""
import time

import pytest

from bus_agent import agent, gtfs
from bus_agent.routing import Router
from bus_agent.web import ROOT, Session, route_geometry

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
    s = Session(router, ROOT / "scenarios/t4_reply_add_alex.json", broadcast=items.append)
    assert s.state()["next"]["n"] == 1
    for _ in range(len(s.sc["events"])):
        assert s.step()
        while s.busy:
            time.sleep(0.01)
    replies = [i["event"]["data"]["text"] for i in items if i["type"] == "trace"
               and i["event"]["agent"] == "concierge" and i["event"]["data"]["to"] == "user"]
    assert replies == ["On it."] * 3  # the user message and two notices; boarding has no notice
    assert s.state()["next"] is None and s.state()["time"] == "09:20"
    assert not s.step()
