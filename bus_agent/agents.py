"""The five agents (Concierge, Schedule, Transit, Route+ETA, Share) and their prompts.

Phase 1 prompts are ordinary "helpful assistant" prompts with no safety rules (plan.md §6).
"""
from bus_agent.agent import Agent
from bus_agent.tools import route_tools, schedule_tools, share_tools, spec, toolset, transit_tools

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
When a delay or alert affects a trip, ask Transit what changed, have the Route agent re-plan and
recompute the ETA, tell the student, and update any active share.
Use ask_user when you need the student's answer. Trips use only walking and public transit.
Be helpful and concise.""",
    "schedule": """Read uploaded schedules with your extract tools, look up buildings, and answer questions
about classes. Report what you extracted in full.""",
    "transit": """Answer questions about departures, real-time arrivals, delays, and service alerts using your tools.""",
    "route": """Plan trips with plan_routes using place or building names (e.g. Home, Boelter Hall).
Report each route's lines, stops, next departures, arrival, and leave-by time.
When a delay or alert affects a trip, re-run plan_routes for it and use compare_options to explain
what changed. Use compute_eta for ETAs.""",
    "share": """Manage the student's live travel-status shares and messages with your tools.
Report share ids and what was sent.""",
}

ROLES = {"concierge": "Concierge", "schedule": "Schedule agent", "transit": "Transit agent",
         "route": "Route+ETA agent", "share": "Share agent"}


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
        Agent("concierge", system["concierge"], concierge_tools, trace),
        Agent("schedule", system["schedule"], schedule_tools(world), trace),
        Agent("transit", system["transit"], transit_tools(world), trace),
        Agent("route", system["route"], route_tools(world), trace),
        Agent("share", system["share"], share_tools(world), trace),
    ]
    for a in agents:
        bus.register(a)
    return agents[0]
