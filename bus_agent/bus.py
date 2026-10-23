"""Inter-agent message routing (hub topology: specialists talk only to the Concierge)."""


class Bus:
    def __init__(self, trace, clock):
        self.trace = trace
        self.clock = clock
        self.agents = {}

    def register(self, agent):
        self.agents[agent.name] = agent

    def send(self, sender, recipient, text, images=None):
        """Deliver a message and return the recipient's reply (also logged as a message)."""
        if "concierge" not in (sender, recipient):
            raise ValueError(f"{sender} -> {recipient}: specialists talk only to the Concierge")
        self.trace.log(sender, "message", {"to": recipient, "text": text})
        reply = self.agents[recipient].run(f"[{self.clock()}] {text}", images=images)
        self.trace.log(recipient, "message", {"to": sender, "text": reply})
        return reply
