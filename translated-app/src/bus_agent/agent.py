"""Tool-calling loop shared by all agents."""
import json

from bus_agent.llm import chat

MAX_STEPS = 12


class Agent:
    """An LLM with a system prompt and tools. Keeps its conversation for the whole session."""

    def __init__(self, name, system, tools, trace, policy_port=None):
        self.name = name
        self.tools = tools  # name -> (schema, fn(**args) -> result)
        self.trace = trace
        self.policy_port = policy_port
        self.history = [{"role": "system", "content": system}]
        self.last_results = []  # [(tool name, result)] from the latest run()

    def run(self, content, images=None):
        self.last_results = []
        msg = {"role": "user", "content": content}
        if images:
            msg["images"] = images
        self.history.append(msg)
        schemas = [schema for schema, _ in self.tools.values()]
        for _ in range(MAX_STEPS):
            reply = chat(self.history, tools=schemas or None, agent=self.name)["message"]
            self.history.append({k: v for k, v in reply.items() if k in ("role", "content", "tool_calls")})
            if reply.get("thinking"):
                self.trace.log(self.name, "thought", reply["thinking"])
            calls = reply.get("tool_calls") or []
            if not calls:
                return reply.get("content", "")
            if reply.get("content"):
                self.trace.log(self.name, "thought", reply["content"])
            for call in calls:
                name, args = call["function"]["name"], call["function"].get("arguments") or {}
                self.trace.log(self.name, "tool_call", {"name": name, "arguments": args})
                result = self._call(name, args)
                self.trace.log(self.name, "tool_result", {"name": name, "result": result})
                self.last_results.append((name, result))
                self.history.append({"role": "tool", "tool_name": name,
                                     "content": json.dumps(result, ensure_ascii=False)})
        return "(stopped: too many tool steps)"

    def _call(self, name, args):
        if name not in self.tools:
            return {"error": f"unknown tool {name}"}
        try:
            callback = self.tools[name][1]
            if self.policy_port is not None:
                return self.policy_port.invoke(self.name, name, args, callback)
            return callback(**args)
        except Exception as e:  # report tool errors to the model instead of crashing the run
            return {"error": f"{type(e).__name__}: {e}"}
