"""Inter-agent message routing (hub topology: specialists talk only to the Concierge).

With pass_through (the Phase 1 default), a specialist's reply to the Concierge also carries the raw
results of the tools it called, so the Concierge sees the data itself and not only a summary. This is
a common multi-agent pattern, and it means text inside tool results (alert text, upload notes)
reaches the agent that can trigger shares.
"""
import json

RAW_LIMIT = 4000  # chars per tool result, to keep the Concierge's context bounded


class Bus:
    def __init__(self, trace, clock, pass_through=True):
        self.trace = trace
        self.clock = clock
        self.pass_through = pass_through
        self.agents = {}

    def register(self, agent):
        self.agents[agent.name] = agent

    def send(self, sender, recipient, text, images=None):
        """Deliver a message and return the recipient's reply (also logged as a message)."""
        if "concierge" not in (sender, recipient):
            raise ValueError(f"{sender} -> {recipient}: specialists talk only to the Concierge")
        self.trace.log(sender, "message", {"to": recipient, "text": text})
        agent = self.agents[recipient]
        reply = agent.run(f"[{self.clock()}] {text}", images=images)
        if self.pass_through and agent.last_results:
            raw = [{"tool": name, "result": _clip(result)} for name, result in agent.last_results]
            reply += "\n\nRaw tool results:\n" + json.dumps(raw, ensure_ascii=False)
        self.trace.log(recipient, "message", {"to": sender, "text": reply})
        return reply


def _clip(result):
    text = json.dumps(result, ensure_ascii=False)
    return result if len(text) <= RAW_LIMIT else text[:RAW_LIMIT] + "…"
