"""Load and trim GTFS feeds (Culver CityBus, LA Metro bus + rail, Big Blue Bus).

`python -m bus_agent.gtfs trim` reads data/gtfs/raw/<feed>.zip and writes the trimmed feed to
data/gtfs/<feed>/. load() reads the trimmed feeds into one Network. All ids are prefixed with the
feed key ("bbb:1234") so feeds never collide.
"""
import csv
import io
import math
import sys
import zipfile
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

GTFS_DIR = Path(__file__).resolve().parent.parent / "data" / "gtfs"

# Westwood / UCLA / Sawtelle / Palms / Culver City / Mar Vista, with margin for 15-min walks.
BBOX = {"lat": (33.975, 34.090), "lon": (-118.485, -118.360)}

# key -> line-name prefix; rail lines have no short name, so they use the long name.
FEEDS = {
    "bbb": "BB",
    "ccb": "CC",
    "metro_bus": "M",
    "metro_rail": "",
}

KEEP = {
    "agency.txt": None,
    "feed_info.txt": None,
    "calendar.txt": None,
    "calendar_dates.txt": None,
    "routes.txt": ["route_id", "route_short_name", "route_long_name", "route_type"],
    "trips.txt": ["route_id", "service_id", "trip_id", "trip_headsign", "direction_id", "shape_id"],
    "stops.txt": ["stop_id", "stop_name", "stop_lat", "stop_lon"],
    "stop_times.txt": ["trip_id", "arrival_time", "departure_time", "stop_id", "stop_sequence"],
    "shapes.txt": ["shape_id", "shape_pt_lat", "shape_pt_lon", "shape_pt_sequence"],
}
SHAPE_MARGIN = 0.01   # deg; keep shape points a little outside BBOX so lines reach the edge
SHAPE_STEP_M = 15     # drop shape points closer than this to the previous kept point (map only)


def _rows(zf, name):
    with zf.open(name) as f:
        yield from csv.DictReader(io.TextIOWrapper(f, "utf-8-sig"))


def _write(path, rows, columns):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, columns, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def _in_bbox(lat, lon):
    return BBOX["lat"][0] <= lat <= BBOX["lat"][1] and BBOX["lon"][0] <= lon <= BBOX["lon"][1]


def trim(key):
    """Keep stops inside BBOX, trips that visit at least two of them, and the routes/services they use."""
    zf = zipfile.ZipFile(GTFS_DIR / "raw" / f"{key}.zip")
    out = GTFS_DIR / key
    out.mkdir(exist_ok=True)

    stops = [s for s in _rows(zf, "stops.txt")
             if s["stop_lat"] and _in_bbox(float(s["stop_lat"]), float(s["stop_lon"]))]
    stop_ids = {s["stop_id"] for s in stops}

    times = defaultdict(list)
    for st in _rows(zf, "stop_times.txt"):
        if st["stop_id"] in stop_ids:
            times[st["trip_id"]].append(st)
    times = {t: rows for t, rows in times.items() if len(rows) >= 2}

    trips = [t for t in _rows(zf, "trips.txt") if t["trip_id"] in times]
    route_ids = {t["route_id"] for t in trips}
    service_ids = {t["service_id"] for t in trips}
    used_stops = {st["stop_id"] for rows in times.values() for st in rows}

    _write(out / "stops.txt", [s for s in stops if s["stop_id"] in used_stops], KEEP["stops.txt"])
    _write(out / "trips.txt", trips, KEEP["trips.txt"])
    _write(out / "routes.txt", [r for r in _rows(zf, "routes.txt") if r["route_id"] in route_ids], KEEP["routes.txt"])
    _write(out / "stop_times.txt", [st for rows in times.values() for st in rows], KEEP["stop_times.txt"])
    if "shapes.txt" in zf.namelist():
        _write(out / "shapes.txt", _trim_shapes(zf, {t["shape_id"] for t in trips if t.get("shape_id")}),
               KEEP["shapes.txt"])
    for name in ("agency.txt", "feed_info.txt", "calendar.txt", "calendar_dates.txt"):
        if name in zf.namelist():
            rows = list(_rows(zf, name))
            if name in ("calendar.txt", "calendar_dates.txt"):
                rows = [r for r in rows if r["service_id"] in service_ids]
            if rows:
                _write(out / name, rows, list(rows[0]))
    return {"stops": len(used_stops), "trips": len(trips), "routes": len(route_ids)}


def _trim_shapes(zf, shape_ids):
    """Shape points of used shapes inside BBOX (+ margin), thinned, for drawing routes on the map."""
    lat0, lat1 = BBOX["lat"][0] - SHAPE_MARGIN, BBOX["lat"][1] + SHAPE_MARGIN
    lon0, lon1 = BBOX["lon"][0] - SHAPE_MARGIN, BBOX["lon"][1] + SHAPE_MARGIN
    points = defaultdict(list)
    for r in _rows(zf, "shapes.txt"):
        if r["shape_id"] in shape_ids:
            lat, lon = float(r["shape_pt_lat"]), float(r["shape_pt_lon"])
            if lat0 <= lat <= lat1 and lon0 <= lon <= lon1:
                points[r["shape_id"]].append((int(r["shape_pt_sequence"]), lat, lon))
    for sid, pts in points.items():
        last = None
        for seq, lat, lon in sorted(pts):
            if last is None or meters(*last, lat, lon) >= SHAPE_STEP_M:
                yield {"shape_id": sid, "shape_pt_lat": f"{lat:.5f}", "shape_pt_lon": f"{lon:.5f}",
                       "shape_pt_sequence": seq}
                last = (lat, lon)


def parse_time(hms):
    """GTFS time ("25:10:00" is allowed) -> seconds after midnight of the service day."""
    h, m, s = hms.strip().split(":")
    return int(h) * 3600 + int(m) * 60 + int(s)


def meters(lat1, lon1, lat2, lon2):
    """Great-circle distance in meters."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 2 * 6371000 * math.asin(math.sqrt(a))


@dataclass
class Stop:
    id: str
    name: str
    lat: float
    lon: float


@dataclass
class Trip:
    id: str
    line: str
    service: str
    direction: str
    headsign: str
    stops: list = field(default_factory=list)  # [(stop_id, arrive_sec, depart_sec)] in order
    shape: str = ""                             # "feed:shape_id", for drawing only


@dataclass
class Network:
    stops: dict = field(default_factory=dict)      # stop_id -> Stop
    lines: dict = field(default_factory=dict)      # line name -> mode ("bus" | "rail")
    trips: dict = field(default_factory=dict)      # trip_id -> Trip
    calendar: dict = field(default_factory=dict)   # service_id -> (start, end, weekdays set)
    exceptions: dict = field(default_factory=dict)  # (service_id, "YYYYMMDD") -> 1 added | 2 removed
    _grid: dict = field(default_factory=lambda: defaultdict(list))

    def services_on(self, day: date):
        """Service ids running on a date (calendar.txt + calendar_dates.txt)."""
        ymd = day.strftime("%Y%m%d")
        active = {sid for sid, (start, end, days) in self.calendar.items()
                  if start <= ymd <= end and day.weekday() in days}
        for (sid, d), kind in self.exceptions.items():
            if d == ymd:
                (active.add if kind == 1 else active.discard)(sid)
        return active

    def index(self):
        for s in self.stops.values():
            self._grid[(round(s.lat, 2), round(s.lon, 2))].append(s)

    def stops_near(self, lat, lon, radius_m):
        """[(Stop, meters)] within radius_m (straight line). Grid cells are 0.01 deg (~1 km)."""
        cells = math.ceil(radius_m / 900)
        cy, cx = round(lat, 2), round(lon, 2)
        found = []
        for dy in range(-cells, cells + 1):
            for dx in range(-cells, cells + 1):
                for s in self._grid.get((round(cy + dy / 100, 2), round(cx + dx / 100, 2)), ()):
                    d = meters(lat, lon, s.lat, s.lon)
                    if d <= radius_m:
                        found.append((s, d))
        return found


def _line_name(prefix, route):
    if not prefix:
        return route["route_long_name"].replace("Metro ", "").strip()
    short = route["route_short_name"].strip() or route["route_id"]
    if prefix == "CC" and short.startswith("Rapid "):  # Culver CityBus "Rapid 6" -> CC6R
        short = short.split()[1] + "R"
    return prefix + short


def _read(path):
    if not path.exists():
        return []
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def load(keys=None, gtfs_dir=GTFS_DIR):
    """Read trimmed feeds into one Network."""
    net = Network()
    for key in keys or FEEDS:
        d = gtfs_dir / key
        prefix = FEEDS.get(key, key.upper())
        lines = {}
        for r in _read(d / "routes.txt"):
            lines[r["route_id"]] = _line_name(prefix, r)
            net.lines[lines[r["route_id"]]] = "rail" if r["route_type"] in ("0", "1", "2") else "bus"
        for s in _read(d / "stops.txt"):
            sid = f"{key}:{s['stop_id']}"
            net.stops[sid] = Stop(sid, s["stop_name"].strip(), float(s["stop_lat"]), float(s["stop_lon"]))
        for c in _read(d / "calendar.txt"):
            days = {i for i, n in enumerate(["monday", "tuesday", "wednesday", "thursday", "friday",
                                             "saturday", "sunday"]) if c[n] == "1"}
            net.calendar[f"{key}:{c['service_id']}"] = (c["start_date"], c["end_date"], days)
        for c in _read(d / "calendar_dates.txt"):
            net.exceptions[(f"{key}:{c['service_id']}", c["date"])] = int(c["exception_type"])
        for t in _read(d / "trips.txt"):
            tid = f"{key}:{t['trip_id']}"
            net.trips[tid] = Trip(tid, lines[t["route_id"]], f"{key}:{t['service_id']}",
                                  t.get("direction_id", ""), t.get("trip_headsign", ""),
                                  shape=f"{key}:{t['shape_id']}" if t.get("shape_id") else "")
        rows = sorted(_read(d / "stop_times.txt"), key=lambda r: (r["trip_id"], int(r["stop_sequence"])))
        for r in rows:
            net.trips[f"{key}:{r['trip_id']}"].stops.append(
                (f"{key}:{r['stop_id']}", parse_time(r["arrival_time"]), parse_time(r["departure_time"])))
    net.index()
    return net


def load_shapes(keys=None, gtfs_dir=GTFS_DIR):
    """{"feed:shape_id": [(lat, lon)]} from the trimmed feeds (used only to draw routes)."""
    shapes = defaultdict(list)
    for key in keys or FEEDS:
        rows = sorted(_read(gtfs_dir / key / "shapes.txt"), key=lambda r: (r["shape_id"], int(r["shape_pt_sequence"])))
        for r in rows:
            shapes[f"{key}:{r['shape_id']}"].append((float(r["shape_pt_lat"]), float(r["shape_pt_lon"])))
    return dict(shapes)


if __name__ == "__main__":
    if sys.argv[1:] == ["trim"]:
        for key in FEEDS:
            print(key, trim(key))
    else:
        print("usage: python -m bus_agent.gtfs trim")
