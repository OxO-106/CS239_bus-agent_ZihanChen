"""Tool-calling bench: does the model pick the right tool with the right arguments?

Usage: python -m bench.tool_calls [--runs N] [--agent NAME]
"""
import argparse
import time

from bus_agent.llm import chat


def tool(name, description, **params):
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "required": list(params),
                       "properties": {k: {"type": "string", "description": v} for k, v in params.items()}}}}


# A realistic mix of tools from plan.md §2, offered together so the model has to choose.
TOOLS = [
    tool("get_realtime_arrivals", "Next real-time arrivals of a line at a stop", line="Line name, e.g. BB1", stop="Stop name"),
    tool("get_service_alerts", "Active service alerts for a line", line="Line name"),
    tool("list_routes", "List transit lines serving a stop", stop="Stop name"),
    tool("plan_routes", "Find all suitable walk+transit routes between two places", origin="Start place", destination="End place", arrive_by="HH:MM"),
    tool("lookup_building", "Coordinates of a UCLA building", building="Building name"),
    tool("walk_time", "Walking minutes between two places", origin="Start place", destination="End place"),
    tool("compute_eta", "ETA for the trip in progress on a route", route_id="Route id"),
    tool("get_contacts", "List the user's saved contacts"),
    tool("create_share", "Start sharing live travel status with a contact", recipient="Contact name", fields="Comma-separated: live_location, route, eta"),
    tool("revoke_share", "Stop an active share", share_id="Share id"),
]

# (prompt, expected tool or None for no call, expected argument substrings)
CASES = [
    ("When is the next BB1 bus at Sawtelle & Ohio?", "get_realtime_arrivals", {"line": "BB1", "stop": "sawtelle"}),
    ("Are there any alerts on the Metro 761 right now?", "get_service_alerts", {"line": "761"}),
    ("Which lines stop at Westwood & Wilshire?", "list_routes", {"stop": "westwood"}),
    ("I need to get from Culver City Station to Boelter Hall by 9:50.", "plan_routes", {"origin": "culver", "destination": "boelter", "arrive_by": "9:50"}),
    ("Where is the Geology Building?", "lookup_building", {"building": "geology"}),
    ("How long does it take to walk from Boelter Hall to Mathematical Sciences?", "walk_time", {"origin": "boelter", "destination": "math"}),
    ("What's my ETA on route BB1:Sawtelle&Ohio>Westwood&Wilshire?", "compute_eta", {"route_id": "BB1"}),
    ("Who are my contacts?", "get_contacts", {}),
    ("Share only my ETA with Mom.", "create_share", {"recipient": "mom", "fields": "eta"}),
    ("Stop sharing, share id s-001.", "revoke_share", {"share_id": "s-001"}),
    ("Thanks, that's all for now!", None, {}),
]


def check(message, expected, args):
    calls = message.get("tool_calls") or []
    if expected is None:
        return not calls, "no call" if not calls else f"called {calls[0]['function']['name']}"
    if not calls:
        return False, "no tool call"
    fn = calls[0]["function"]
    if fn["name"] != expected:
        return False, f"wrong tool {fn['name']}"
    got = {k: str(v).lower() for k, v in fn["arguments"].items()}
    missing = [k for k, v in args.items() if v.lower() not in got.get(k, "")]
    return not missing, f"args {fn['arguments']}" + (f" (missing {missing})" if missing else "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--agent", default=None, help="use MODEL_<AGENT>/THINK_<AGENT> overrides")
    opts = ap.parse_args()

    passed = total = 0
    latencies = []
    for prompt, expected, args in CASES:
        results = []
        for _ in range(opts.runs):
            t = time.time()
            out = chat([{"role": "user", "content": prompt}], tools=TOOLS, agent=opts.agent)
            latencies.append(time.time() - t)
            results.append(check(out["message"], expected, args))
        ok = sum(r[0] for r in results)
        passed += ok
        total += opts.runs
        print(f"{ok}/{opts.runs}  {prompt}\n      {results[-1][1]}")
    latencies.sort()
    print(f"\nTOTAL {passed}/{total}  median latency {latencies[len(latencies) // 2]:.2f}s")


if __name__ == "__main__":
    main()
