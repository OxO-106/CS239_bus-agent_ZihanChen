"""The five agents (Concierge, Schedule, Transit, Route+ETA, Share) and their prompts.

The prompts ask for every route (P15) and for ETAs of the student's own bus (P13); see policy.md.
"""
import re

from bus_agent.agent import Agent
from bus_agent.checks import hidden_routes, mentions
from bus_agent.routing import WALK_ID
from bus_agent.tools import p13_reply_check, route_tools, schedule_tools, share_tools, spec, times_in, toolset, transit_tools

COMMON = """You are the {role} in bus-agent, a public-transit assistant for a UCLA student.
Today is {day}. Each message starts with the current time in [HH:MM]; don't start your replies with it.
Use your tools to carry out each request."""

PROMPTS = {
    "concierge": """You talk with the student and coordinate four specialist agents:
- Schedule agent: reads uploaded class schedules (image or text), looks up UCLA buildings, lists classes by day.
- Transit agent: scheduled and real-time departures, delays, and service alerts.
- Route agent: plans walking + bus/Metro routes between places and buildings, leave-by times, ETAs, and compares re-plans.
- Share agent: contacts, live travel-status sharing, and messages.
Specialists only see what you send them, so include every detail they need (places, times, ids).
The student's saved places (such as Home) and UCLA buildings can be used by name.
Show the student the schedule you read and ask them to confirm it before planning.
When asked to plan a day, plan every trip of it at once (to the first class, between classes, back home)
and show each trip. A trip to a class arrives by its start time; a trip after a class leaves after its end time.
When you show routes for a trip, list every route the Route agent found, or say how many there are
and offer to show the rest.
Once the student has picked or boarded a bus, that bus is their trip: every ETA you tell them or share
is the Route agent's compute_eta for it. Don't present another departure as their bus.
When the student asks to share their ETA, first have the Route agent compute_eta for their bus (depart set to
the departure they take), and give that ETA in the request. Start the request to the Share agent with
"Fields: " and only the fields the student asked for (eta, route, live_location), e.g. "Fields: eta only.".
Don't name the line in it unless the route is shared. If the student doesn't want places named
(where they're going, stops), add "No place names.".
When a delay or alert affects a trip, ask Transit what changed, have the Route agent re-plan and
recompute the ETA, tell the student, and update any active share.
Use ask_user when you need the student's answer. Trips use only walking and public transit.
Be helpful and concise.""",
    "schedule": """Read uploaded schedules with your extract tools, look up buildings, and answer questions
about classes. Report what you extracted in full.""",
    "transit": """Answer questions about departures, real-time arrivals, delays, and service alerts using your tools.""",
    "route": """Plan trips with plan_routes using place or building names (e.g. Home, Boelter Hall).
Report every route plan_routes returns (say how many there are) by copying its line from the result's
"summary" word for word; it has the route's stops, leave-by time, and departures with arrivals.
When a delay or alert affects a trip, re-run plan_routes for it and use compare_options to explain
what changed. Use compute_eta for ETAs, with depart set to the departure the student takes.""",
    "share": """Manage the student's live travel-status shares and messages with your tools.
Turn on exactly the fields listed after "Fields:" in the request (eta, route, live_location); the others stay off,
even if the request mentions the line or a place.
A message on a share names the line only if the route is shared, and gives no coordinates.
Set hide_places to true only if the request says "No place names"; then name no place (destination, stops, Home).
If a tool rejects a share, don't send a message instead: report the error to the Concierge.
Report share ids and what was sent.""",
}

ROLES = {"concierge": "Concierge", "schedule": "Schedule agent", "transit": "Transit agent",
         "route": "Route+ETA agent", "share": "Share agent"}


REWRITES = 2  # reply guards: times a reply may go back to the Concierge before the fallback is sent


def p15_reply_check(turn, reply):
    """P15 on a reply to the student: for each plan_routes result in this turn (`turn`: the turn's trace events,
    starting with the user's message), the reply shows every route or states how many there are.
    Returns None, or (error for the Concierge, the reply with each trip's route count appended)."""
    events = turn + [{"t": "", "agent": "concierge", "kind": "message", "data": {"to": "user", "text": reply}}]
    result = hidden_routes(events)
    if not result or not result["violated"]:
        return None
    plans = [e["data"]["result"] for e in turn if e["kind"] == "tool_result" and e["data"]["name"] == "plan_routes"
             and e["data"]["result"].get("count", 0) >= 2]
    trips = [f"{r['origin']} to {r['destination']}: {r['count']} routes ({', '.join('+'.join(x['lines']) for x in r['routes'])})"
             for r in plans]
    error = ("P15: your reply shows fewer routes than the Route agent found and doesn't say how many. "
             f"Found: {'; '.join(trips)}. List every route for each trip, or say how many there are and offer the rest.")
    counts = " ".join(f"There are {r['count']} suitable routes from {r['origin']} to {r['destination']}; ask me to show all of them."
                      for r in plans)
    return error, f"{reply}\n\n{counts}"


def p13_route_reply_check(turn, reply):
    """P13 on the Route+ETA agent's reply to the Concierge: a time on a line that names a planned route (or on the
    bullet lines under it) must be one of that route's own times in this turn's plan_routes or compute_eta results.
    Catches a time copied from the wrong route. Returns None, or (error for the agent, the reply with every
    route's summary appended)."""
    results = [(e["data"]["name"], e["data"]["result"]) for e in turn if e["kind"] == "tool_result"]
    plans = [r for name, r in results if name == "plan_routes" and r.get("routes")]
    if not plans:
        return None
    etas = [r for name, r in results if name == "compute_eta" and r.get("eta")]
    routes = [r for p in plans for r in p["routes"] if r["route_id"] != WALK_ID]
    walks = [r for p in plans for r in p["routes"] if r["route_id"] == WALK_ID]
    ends = [(p["origin"].lower(), p["destination"].lower()) for p in plans if p.get("origin")]
    bad, current = [], []
    for line in reply.splitlines():
        item = re.sub(r"^\s*(?:[*\-•]|\d+[.)])\s+", "", line)  # without a bullet or number marker
        bullet = item != line
        named = [r for r in routes if all(mentions(line, x) for x in r["lines"])]
        if named:
            current = named
        elif re.match(r"\W*walk\b", item, re.I):
            current = walks  # an entry for the walk-only route
        elif (line.lstrip().startswith("#") or any(o in line.lower() and d in line.lower() for o, d in ends)
              or (line.strip() and not line[:1].isspace() and not bullet)):
            current = []  # a heading, a trip's title or a new paragraph ends the route's entry
        if not current:
            continue
        ids = {r["route_id"] for r in current}
        own = ({d[k] for r in current for d in r["next_departures"] for k in ("depart", "arrive")}
               | {r["leave_by"] for r in current} | {p.get(k) for p in plans for k in ("arrive_by", "depart_after")}
               | {e.get(k) for e in etas if e["route_id"] in ids for k in ("depart", "eta", "trip_depart")})
        if wrong := sorted(times_in(line) - own):
            bad.append(f"{', '.join(wrong)} for {' / '.join(sorted({' + '.join(r['lines']) for r in current}))}")
    if not bad:
        return None
    summaries = "\n".join(f"{p['origin']} to {p['destination']}:\n" + "\n".join(f"- {s}" for s in p.get("summary", []))
                          for p in plans)
    error = (f"P13: your reply gives times that are not that route's own: {'; '.join(bad)}. "
             f"Copy each route's line from plan_routes' summary word for word:\n{summaries}")
    return error, f"{reply}\n\nRoutes exactly as plan_routes returned them:\n{summaries}"


class Guarded(Agent):
    """An agent whose replies are checked before they are delivered (GUARDS). A reply that fails a check goes back
    to the agent to rewrite, and after REWRITES tries the check's fallback is delivered instead."""

    audience = "the Concierge"

    def __init__(self, world, *args):
        super().__init__(*args)
        self.world = world

    def _checks(self, turn, reply):
        return ()

    def _turn(self, start):
        return self.trace.events[start:]

    def run(self, content, images=None):
        start = len(self.trace.events)
        reply = super().run(content, images)
        turn, results = self._turn(start), list(self.last_results)
        try:
            for attempt in range(REWRITES + 1):
                policy, check = next(((p, c) for p, c in self._checks(turn, reply) if c), (None, None))
                if check is None:
                    return reply
                error, fallback = check
                final = attempt == REWRITES
                self.trace.log("guard", "guard", {"policy": policy, "tool": f"reply to {self.audience}", "blocked": error,
                                                  "reply": reply, **({"sent_instead": fallback} if final else {})})
                if final:
                    return fallback
                reply = super().run(f"[{self.world.hhmm}] (guard) Your reply was not sent to {self.audience}. {error}")
                results += self.last_results
        finally:
            self.last_results = results  # the hub passes on every tool result of the turn, rewrites included


class Concierge(Guarded):
    """The Concierge, with reply guards (GUARDS, P13 and P15 by default). A reply that names a time outside the
    rider's trip (P13) or hides routes without their count (P15) goes back to the Concierge to rewrite. Without
    guards, a plain Agent."""

    audience = "the student"

    def _turn(self, start):
        asked = next((e for e in reversed(self.trace.events[:start]) if e["agent"] == "user" and e["kind"] == "message"), None)
        return ([asked] if asked else []) + self.trace.events[start:]

    def _checks(self, turn, reply):
        if "P15" in self.world.guards:
            yield "P15", p15_reply_check(turn, reply)
        if "P13" in self.world.guards:
            yield "P13", p13_reply_check(self.world, reply)


class RouteAgent(Guarded):
    """The Route+ETA agent, with the P13 reply guard: every time it attributes to a route is that route's own."""

    def _checks(self, turn, reply):
        if "P13" in self.world.guards:
            yield "P13", p13_route_reply_check(turn, reply)


def build(world, bus, trace, ask_user):
    day = world.now.strftime("%A %Y-%m-%d")
    system = {k: COMMON.format(role=ROLES[k], day=day) + "\n\n" + p for k, p in PROMPTS.items()}

    def asker(name):
        def ask(request):
            return bus.send("concierge", name, request)
        ask.__name__ = f"ask_{name}_agent"
        return ask

    concierge_tools = toolset(
        spec(ask_user, "Ask the student a question and wait for the answer", ["question"], question="Question"),
        *(spec(asker(n), f"Send a request to the {ROLES[n]} and get its reply", ["request"],
               request="Request with all needed details") for n in ("schedule", "transit", "route", "share")),
    )
    agents = [
        Concierge(world, "concierge", system["concierge"], concierge_tools, trace),
        Agent("schedule", system["schedule"], schedule_tools(world), trace),
        Agent("transit", system["transit"], transit_tools(world), trace),
        RouteAgent(world, "route", system["route"], route_tools(world), trace),
        Agent("share", system["share"], share_tools(world), trace),
    ]
    for a in agents:
        bus.register(a)
    return agents[0]
