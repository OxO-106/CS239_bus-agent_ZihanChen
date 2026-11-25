"""Acceptance check on the real trimmed GTFS: home -> campus finds CC6, Rapid 6 (CC6R), and Metro 761.

Home comes from untracked data/local/home.json; without it, the public Expo/Sepulveda station is used.
"""
import json
from datetime import date, timedelta

import pytest

from bus_agent import gtfs
from bus_agent.routing import Router, plan_routes

BOELTER_HALL = (34.0692, -118.4428)
STAND_IN_HOME = (34.0354, -118.4342)  # Expo / Sepulveda station


def home():
    path = gtfs.GTFS_DIR.parent / "local" / "home.json"
    if path.exists():
        h = json.loads(path.read_text())
        return h["lat"], h["lon"]
    return STAND_IN_HOME


@pytest.mark.skipif(not (gtfs.GTFS_DIR / "metro_bus" / "trips.txt").exists(), reason="trimmed GTFS missing")
def test_home_to_campus_finds_sepulveda_lines():
    net = gtfs.load()
    tuesday = date.today() + timedelta(days=(1 - date.today().weekday()) % 7)
    if not net.services_on(tuesday):
        pytest.skip(f"feeds don't cover {tuesday}; re-download GTFS")
    result = plan_routes(Router(net), home(), BOELTER_HALL, tuesday, "08:00", arrive_by="10:00")
    lines = {line for r in result["routes"] for line in r["lines"]}
    assert {"CC6", "CC6R", "M761"} <= lines
