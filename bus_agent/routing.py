"""Route search (plan_routes), stable route IDs, and route-set diffs (compare_options).

A route is one to three lines (up to two transfers) plus board/alight stops (plan.md §3).
It is suitable if every walk is within the walk limit (transfer walks <= 3 min), it still runs
today, and no active alert closes a stop it uses. Speed is not a filter. Which transfer counts
are listed: all routes with the fewest transfers that work; if fewer than 3 of them arrive in
time, also those with one more transfer (see plan_routes).

Search is structural first (which lines connect stops near origin and destination), then the
day's timetable decides departures; routes that can't run are returned in `excluded` with a reason.
"""
import math
import re
from collections import defaultdict

from bus_agent.gtfs import meters

WALK_M_PER_MIN = 80     # ~4.8 km/h
DETOUR = 1.3            # street distance / straight-line distance
MAX_WALK = 10
LONG_WALK = 15          # "show more"
MAX_TRANSFER_WALK = 3
MIN_TRANSFER_BUFFER = 60  # seconds on top of the transfer walk
MIN_OPTIONS = 3         # fewer in-time routes than this at the fewest transfers -> also list one more transfer
MAX_TRANSFERS = 2


def walk_min(m):
    return m * DETOUR / WALK_M_PER_MIN


def walk_radius(minutes):
    return minutes * WALK_M_PER_MIN / DETOUR


def hhmm(sec):
    sec = int(sec) % 86400
    return f"{sec // 3600:02d}:{sec % 3600 // 60:02d}"


def parse_hhmm(text):
    h, m = text.split(":")
    return int(h) * 3600 + int(m) * 60


def clean_name(name):
    """'PICO EB & SEPULVEDA NS (Sepulveda Station)' -> 'Pico & Sepulveda'."""
    name = re.sub(r"\(.*?\)", "", name)
    name = re.sub(r"\b(NB|SB|EB|WB|NS|FS|MB)\b", "", name)
    name = re.sub(r"\s*(/|&|@|\band\b)\s*", " & ", name)
    name = re.sub(r"\s+", " ", name).strip(" &")
    return name.title() if name.isupper() else name


def _short(name):
    name = re.sub(r"\s+station$", "", clean_name(name), flags=re.I)
    return name.replace(" & ", "&").replace(" ", "")


class Router:
    def __init__(self, net):
        self.net = net
        self.by_line = defaultdict(list)
        self.pos = {}
        # line -> {(stop sequence): representative trip}; one entry per distinct stop pattern
        self.patterns = defaultdict(dict)
        for t in net.trips.values():
            self.by_line[t.line].append(t)
            p = {}
            for i, (sid, _, _) in enumerate(t.stops):
                p.setdefault(sid, i)
            self.pos[t.id] = p
            self.patterns[t.line].setdefault(tuple(s for s, _, _ in t.stops), t)

    def route_id(self, legs):
        return "|".join(f"{line}:{_short(self.net.stops[b].name)}>{_short(self.net.stops[a].name)}"
                        for line, b, a in legs)

    def _near(self, point, max_walk, closed):
        return {s.id: walk_min(d) for s, d in self.net.stops_near(point[0], point[1], walk_radius(max_walk))
                if s.id not in closed}

    def search(self, origin, dest, max_walk=MAX_WALK, closed=()):
        """Direct and one-transfer candidates: [{"legs": [(line, board, alight)], "walk": (to, transfer, from)}]."""
        O, D, direct, reach_a, reach_b = self._reach(origin, dest, max_walk, closed)
        direct_lines = {line for line, _ in direct}
        transfers = {}
        for sk, a_lines in reach_a.items():
            a_lines = {l: v for l, v in a_lines.items() if l not in direct_lines}
            if not a_lines:
                continue
            stop = self.net.stops[sk]
            for sm_stop, d in self.net.stops_near(stop.lat, stop.lon, walk_radius(MAX_TRANSFER_WALK)):
                b_lines = reach_b.get(sm_stop.id)
                if not b_lines:
                    continue
                tw = walk_min(d)
                for la, (ca, board) in a_lines.items():
                    for lb, (cb, alight) in b_lines.items():
                        if lb == la or lb in direct_lines:
                            continue
                        total = ca + tw + cb
                        if (la, lb) not in transfers or total < transfers[(la, lb)][0]:
                            transfers[(la, lb)] = (total, {
                                "legs": [(la, board, sk), (lb, sm_stop.id, alight)],
                                "walk": (O[board], tw, D[alight])})
        return [opt for _, opt in direct.values()] + [opt for _, opt in transfers.values()]

    def search2(self, origin, dest, max_walk=MAX_WALK, closed=()):
        """Two-transfer candidates: a line from the origin, a middle line, a line to the destination.

        Each walk between lines is <= MAX_TRANSFER_WALK; no line goes direct. Keeps the cheapest first
        line per (middle, last) pair, so each pair of later lines appears once.
        """
        O, D, direct, reach_a, reach_b = self._reach(origin, dest, max_walk, closed)
        direct_lines = {line for line, _ in direct}
        radius = walk_radius(MAX_TRANSFER_WALK)
        # stop -> {first line: (cost to stand at this stop, board, alight of first line, transfer walk)}
        near_a = defaultdict(dict)
        for sk, lines in reach_a.items():
            stop = self.net.stops[sk]
            for s2, d in self.net.stops_near(stop.lat, stop.lon, radius):
                for la, (ca, board) in lines.items():
                    cost = ca + walk_min(d)
                    if s2.id not in closed and la not in direct_lines and (
                            la not in near_a[s2.id] or cost < near_a[s2.id][la][0]):
                        near_a[s2.id][la] = (cost, board, sk, walk_min(d))
        # stop -> {last line: (cost from this stop to the door, board of last line, alight, transfer walk)}
        near_b = defaultdict(dict)
        for sm, lines in reach_b.items():
            stop = self.net.stops[sm]
            for s2, d in self.net.stops_near(stop.lat, stop.lon, radius):
                for lc, (cc, alight) in lines.items():
                    cost = cc + walk_min(d)
                    if s2.id not in closed and lc not in direct_lines and (
                            lc not in near_b[s2.id] or cost < near_b[s2.id][lc][0]):
                        near_b[s2.id][lc] = (cost, sm, alight, walk_min(d))
        found = {}
        for lb, pats in self.patterns.items():
            if lb in direct_lines:
                continue
            for stops, trip in pats.items():
                best = {}  # first line -> (cost minus boarding time on lb, boarding index)
                for j, s in enumerate(stops):
                    if s in closed:
                        continue
                    for lc, (cc, sm, alight, tw2) in near_b.get(s, {}).items():
                        if lc == lb:
                            continue
                        for la, (base, i) in best.items():
                            total = base + trip.stops[j][1] / 60 + cc
                            if la != lc and ((lb, lc) not in found or total < found[(lb, lc)][0]):
                                _, board, sk, tw1 = near_a[stops[i]][la]
                                found[(lb, lc)] = (total, {
                                    "legs": [(la, board, sk), (lb, stops[i], s), (lc, sm, alight)],
                                    "walk": (O[board], tw1 + tw2, D[alight]), "transfer_walks": [tw1, tw2]})
                    for la, (ca, _, _, _) in near_a.get(s, {}).items():
                        base = ca - trip.stops[j][2] / 60
                        if la != lb and (la not in best or base < best[la][0]):
                            best[la] = (base, j)
        return [opt for _, opt in found.values()]

    def find(self, origin, dest, route_id, max_walk=MAX_WALK):
        """The candidate with this route_id (direct, one or two transfers), or None."""
        for search in (self.search, self.search2):
            for opt in search(origin, dest, max_walk):
                if self.route_id(opt["legs"]) == route_id:
                    return opt
        return None

    def _reach(self, origin, dest, max_walk, closed):
        """Stops near each end, direct routes, and the cheapest one-line reach from the origin / to the destination."""
        O, D = self._near(origin, max_walk, closed), self._near(dest, max_walk, closed)
        direct, reach_a, reach_b = {}, defaultdict(dict), defaultdict(dict)

        for line, pats in self.patterns.items():
            for stops, trip in pats.items():
                times = trip.stops
                for i, s in enumerate(stops):
                    if s not in O:
                        continue
                    for k in range(i + 1, len(stops)):
                        sk = stops[k]
                        if sk in closed:
                            continue
                        ride = (times[k][1] - times[i][2]) / 60
                        cost = O[s] + ride
                        if sk in D:
                            key = (line, trip.direction)
                            total = cost + D[sk]
                            if key not in direct or total < direct[key][0]:
                                direct[key] = (total, {"legs": [(line, s, sk)], "walk": (O[s], 0, D[sk])})
                        prev = reach_a[sk].get(line)
                        if prev is None or cost < prev[0]:
                            reach_a[sk][line] = (cost, s)
                for j, s in enumerate(stops):
                    if s not in D:
                        continue
                    for m in range(j):
                        sm = stops[m]
                        if sm in closed:
                            continue
                        cost = (times[j][1] - times[m][2]) / 60 + D[s]
                        prev = reach_b[sm].get(line)
                        if prev is None or cost < prev[0]:
                            reach_b[sm][line] = (cost, s)

        return O, D, direct, reach_a, reach_b

    def _leg_trips(self, line, board, alight, services, delays):
        """[(depart_board, arrive_alight, trip_id)] for today's trips of line serving board then alight."""
        out = []
        for t in self.by_line[line]:
            if t.service not in services:
                continue
            p = self.pos[t.id]
            if board in p and alight in p and p[board] < p[alight]:
                late = delays.get(t.id, 0)
                out.append((t.stops[p[board]][2] + late, t.stops[p[alight]][1] + late, t.id))
        return sorted(out)

    def departures(self, opt, services, now, count=2, delays=None):
        """(next departures, reason if none). Each departure: (leave, board, arrive_door)."""
        delays = delays or {}
        to_stop, tw, from_stop = opt["walk"]
        transfer_walks = opt.get("transfer_walks") or [tw] * (len(opt["legs"]) - 1)
        legs = [self._leg_trips(*leg, services, delays) for leg in opt["legs"]]
        if any(not leg for leg in legs):
            return [], "not_running_today"
        found = []
        for dep, arr, _ in legs[0]:
            leave = dep - math.ceil(to_stop) * 60
            if leave < now:
                continue
            missed = False
            for leg, walk in zip(legs[1:], transfer_walks):
                ready = arr + math.ceil(walk) * 60 + MIN_TRANSFER_BUFFER
                nxt = next((b for b in leg if b[0] >= ready), None)
                if nxt is None:
                    missed = True
                    break
                arr = nxt[1]
            if missed:  # no later connection today, so no later first-leg trip will connect either
                break
            found.append((leave, dep, arr + math.ceil(from_stop) * 60))
            if len(found) == count:
                break
        return found, None if found else "last_trip_passed"

    def describe(self, opt, deps, arrive_by):
        to_stop, tw, from_stop = opt["walk"]
        return {
            "route_id": self.route_id(opt["legs"]),
            "lines": [line for line, _, _ in opt["legs"]],
            "transfers": len(opt["legs"]) - 1,
            "legs": [{"line": line, "board": clean_name(self.net.stops[b].name),
                      "alight": clean_name(self.net.stops[a].name)}
                     for line, b, a in opt["legs"]],
            "walk_min": {"to_stop": math.ceil(to_stop), "transfer": math.ceil(tw),
                         "from_stop": math.ceil(from_stop)},
            "next_departures": [{"depart": hhmm(dep), "arrive": hhmm(arr),
                                 "on_time_for_class": arrive_by is None or arr <= arrive_by,
                                 "realtime": False} for _, dep, arr in deps],
            "leave_by": hhmm(deps[0][0]),
            "labels": [],
            "_sort": (deps[0][2], deps[0][2] - deps[0][0]),
        }


def plan_routes(router, origin, dest, day, now, arrive_by=None, max_walk=MAX_WALK,
                closed_stops=None, delays=None, count=2):
    """List every suitable route from origin to dest (lat, lon) on `day`, leaving at or after `now`.

    now / arrive_by: "HH:MM" or seconds. closed_stops: {stop_id: alert_id}. delays: {trip_id: seconds}.
    `next_departures[].arrive` is arrival at the destination door (walk included). With arrive_by, they are
    the LATEST departures that still arrive by then, latest first, so the rider doesn't arrive far too early;
    a route with none in time lists its next departures and is labeled "arrives late".

    Listed: every working route with the fewest transfers (0, else 1, else 2). If fewer than MIN_OPTIONS
    of those arrive in time, routes with one more transfer are listed too. Working routes left out by
    this rule go in `excluded` with reason "more_transfers_than_needed".
    Returns {"count", "routes", "excluded": [{"route_id", "reason"}]}.
    """
    now = parse_hhmm(now) if isinstance(now, str) else now
    arrive_by = parse_hhmm(arrive_by) if isinstance(arrive_by, str) else arrive_by
    closed = closed_stops or {}
    services = router.net.services_on(day)

    open_opts = router.search(origin, dest, max_walk, closed)
    excluded = []
    by_transfers = {0: [o for o in open_opts if len(o["legs"]) == 1], 1: [o for o in open_opts if len(o["legs"]) == 2]}
    working = {}  # transfers -> described routes that run

    def tier(k):
        if k not in working:
            if k == 2:
                by_transfers[2] = router.search2(origin, dest, max_walk, closed)
            working[k] = []
            for opt in by_transfers[k]:
                deps, reason = router.departures(opt, services, now, count, delays)
                if deps and arrive_by is not None:
                    deps = _latest_in_time(router, opt, services, now, arrive_by, count, delays) or deps
                if deps:
                    working[k].append(router.describe(opt, deps, arrive_by))
                else:
                    excluded.append({"route_id": router.route_id(opt["legs"]), "reason": reason})
        return working[k]

    def in_time(rs):
        return [r for r in rs if any(d["on_time_for_class"] for d in r["next_departures"])]

    tier(0), tier(1)  # always described, so hidden ones can be reported with a reason
    fewest = next((k for k in range(MAX_TRANSFERS + 1) if tier(k)), None)
    routes = []
    if fewest is not None:
        routes = list(tier(fewest))
        if len(in_time(routes)) < MIN_OPTIONS and fewest < MAX_TRANSFERS:
            routes += tier(fewest + 1)
    listed = {r["route_id"] for r in routes}
    excluded += [{"route_id": r["route_id"], "reason": "more_transfers_than_needed"}
                 for rs in working.values() for r in rs if r["route_id"] not in listed]
    if closed:
        open_ids = {router.route_id(o["legs"]) for o in open_opts}
        for opt in router.search(origin, dest, max_walk):
            rid = router.route_id(opt["legs"])
            hit = next((closed[s] for leg in opt["legs"] for s in leg[1:] if s in closed), None)
            if rid not in open_ids and hit:
                excluded.append({"route_id": rid, "reason": f"stop_closed:{hit}"})

    routes.sort(key=lambda r: r.pop("_sort"))
    if routes:
        door = [(parse_hhmm(r["next_departures"][0]["arrive"]) - parse_hhmm(r["leave_by"])) % 86400
                for r in routes]
        walks = [sum(r["walk_min"].values()) for r in routes]
        on_time = [r["next_departures"][0]["on_time_for_class"] for r in routes]
        # "fastest" is the shortest door-to-door trip, among on-time routes if there are any
        best = min(d for d, ok in zip(door, on_time) if ok or not any(on_time))
        for r, d, w, ok in zip(routes, door, walks, on_time):
            if d == best and (ok or not any(on_time)):
                r["labels"].append("fastest")
            if r["transfers"] == 0:
                r["labels"].append("no transfer")
            if w == min(walks):
                r["labels"].append("least walking")
            if max(r["walk_min"].values()) > MAX_WALK:
                r["labels"].append("longer walk")
            if not any(dep["on_time_for_class"] for dep in r["next_departures"]):
                r["labels"].append("arrives late")
    return {"count": len(routes), "routes": routes, "excluded": excluded}


def _latest_in_time(router, opt, services, now, arrive_by, count, delays):
    """The last `count` departures arriving by arrive_by, latest first ([] if none)."""
    every, _ = router.departures(opt, services, now, 10_000, delays)
    return [d for d in every if d[2] <= arrive_by][-count:][::-1]


def compare_options(prev, curr):
    """Diff two plan_routes results. Every previous route is kept, changed, or dropped (with a reason)."""
    now = {r["route_id"]: r for r in curr["routes"]}
    why = {e["route_id"]: e["reason"] for e in curr["excluded"]}
    diff = []
    for r in prev["routes"]:
        rid = r["route_id"]
        if rid in now:
            same = r["next_departures"] == now[rid]["next_departures"]
            diff.append({"route_id": rid, "status": "kept" if same else "changed"})
        else:
            diff.append({"route_id": rid, "status": "dropped", "reason": why.get(rid, "not_found")})
    before = {r["route_id"] for r in prev["routes"]}
    diff += [{"route_id": rid, "status": "new"} for rid in now if rid not in before]
    return diff
