"""Session — the deep dispatcher for BBS conversations.

Owns the map from a conversation topic to the flow that runs it, and drives one
step of that flow. Its interface is small:

    session.handles(command)                  -> bool
    session.advance(command, message, state, deps) -> FlowResult
    session.show(menu_name, deps)             -> FlowResult   (a menu)
    session.enter(topic, deps)                -> FlowResult   (a flow's opening)

The router hands off to it and does the sending; every dispatch decision for a
migrated topic lives behind this seam. Topics not yet registered fall through
to the legacy path.
"""

from flows.bulletin import BulletinFlow
from flows.channel import ChannelFlow
from flows.mail import MailFlow
from flows.navigation import NavigationFlow
from flows.stats import StatsFlow


def _topics(flow):
    """A flow claims one topic (TOPIC) or several (TOPICS)."""
    topics = getattr(flow, "TOPICS", None)
    return list(topics) if topics is not None else [flow.TOPIC]


def _default_flows():
    return [NavigationFlow(), StatsFlow(), BulletinFlow(), MailFlow(), ChannelFlow()]


class Session:
    def __init__(self, flows=None):
        flows = flows if flows is not None else _default_flows()
        self._flows = {}
        for flow in flows:
            for topic in _topics(flow):
                self._flows[topic] = flow
        self._navigation = next((f for f in flows if isinstance(f, NavigationFlow)), None)

    def handles(self, command):
        return command in self._flows

    def advance(self, command, message, state, deps):
        return self._flows[command].advance(message, state, deps)

    def show(self, menu_name, deps):
        """Render a menu. Navigation owns every menu the BBS has."""
        return self._navigation.show(menu_name, deps)

    def enter(self, topic, deps):
        """Ask the flow that owns `topic` for its greeting and starting state."""
        return self._flows[topic].entry(deps)
