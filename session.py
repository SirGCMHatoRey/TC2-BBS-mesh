"""Session — the deep dispatcher for BBS conversations.

Owns the map from a conversation topic to the flow that runs it, and drives
one step of that flow. Its interface is deliberately small:

    session.handles(command) -> bool
    session.advance(command, message, state, deps) -> FlowResult

The router hands off to it and does the sending; every dispatch decision for
a migrated topic lives behind this seam. Flows are migrated into the registry
one at a time — anything not yet registered falls through to the legacy path.
"""

from flows.stats import StatsFlow
from flows.bulletin import BulletinFlow
from flows.mail import MailFlow


def _topics(flow):
    """A flow claims one topic (TOPIC) or several (TOPICS)."""
    topics = getattr(flow, "TOPICS", None)
    return list(topics) if topics is not None else [flow.TOPIC]


class Session:
    def __init__(self, flows=None):
        flows = flows if flows is not None else [StatsFlow(), BulletinFlow(), MailFlow()]
        self._flows = {}
        for flow in flows:
            for topic in _topics(flow):
                self._flows[topic] = flow

    def handles(self, command):
        return command in self._flows

    def advance(self, command, message, state, deps):
        return self._flows[command].advance(message, state, deps)
