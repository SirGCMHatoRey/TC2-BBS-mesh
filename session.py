"""Session — where every Node stands in its conversation, and how it advances.

The Session owns the per-node state (the topic, step, and half-entered content
that CONTEXT.md calls a Session) and the map from a topic to the flow that runs
it. Its interface is one method:

    session.advance(node, message, deps) -> [(destination, text), ...]

The router feeds a message in and sends the outbound messages out; it never
learns what a step is. Because the state lives on the object rather than in a
module global, two Sessions are independent and a test constructs one instead
of clearing a global (see docs/adr/0004).
"""

from flows.base import GOTO_MAIN, Stay, End, Keep, Goto, Enter
from flows.bulletin import BulletinFlow
from flows.channel import ChannelFlow
from flows.js8 import Js8Flow
from flows.mail import MailFlow
from flows.navigation import NavigationFlow
from flows.stats import StatsFlow


def _topics(flow):
    """A flow claims one topic (TOPIC) or several (TOPICS)."""
    topics = getattr(flow, "TOPICS", None)
    return list(topics) if topics is not None else [flow.TOPIC]


def _default_flows():
    return [NavigationFlow(), StatsFlow(), BulletinFlow(), MailFlow(), ChannelFlow(), Js8Flow()]


class Session:
    def __init__(self, flows=None):
        flows = flows if flows is not None else _default_flows()
        self._states = {}                 # node -> its current conversation state

        self._flows = {}
        for flow in flows:
            for topic in _topics(flow):
                self._flows[topic] = flow
        self._navigation = next((f for f in flows if isinstance(f, NavigationFlow)), None)

        self._quick = {}
        for flow in flows:
            for prefix, method in getattr(flow, "QUICK_COMMANDS", {}).items():
                self._quick[prefix] = (flow, method)
        # Longest prefix wins, so "chp,," is never shadowed by a shorter one.
        self._quick_prefixes = sorted(self._quick, key=len, reverse=True)

    def advance(self, node, message, deps):
        """Advance `node`'s conversation by one message.

        Returns the outbound messages the router should send, as
        (destination, text) pairs — the node's replies plus any notification to
        another node. Updates this node's stored state as a side effect.
        """
        result = self._route(node, message, deps)
        return self._enact(node, result, deps)

    # --- routing ----------------------------------------------------------

    def _route(self, node, message, deps):
        # Routing decisions read a stripped, lowercased copy, but the flow
        # itself receives the raw message: a content-capture step (a mail body,
        # a bulletin body) stores it verbatim, so leading whitespace and blank
        # lines must survive. Menu steps strip what they compare themselves.
        stripped = message.strip()
        lowered = stripped.lower()
        # Tolerate a repeated final character on single-letter commands (e.g. "rx").
        if len(lowered) == 2 and lowered[1] == 'x':
            lowered = lowered[0]

        # Quick commands act from anywhere, without moving the conversation.
        result = self._quick_command(stripped, deps)
        if result is not None:
            return result

        # EXIT from anywhere returns to the main menu, before any flow sees it.
        if lowered == 'x':
            return self._navigation.show(GOTO_MAIN, deps)

        # No stored state means the node is sitting at the main menu.
        state = self._states.get(node)
        topic = state['command'] if state else 'MAIN_MENU'
        if topic not in self._flows:
            return self._navigation.show(GOTO_MAIN, deps)
        return self._flows[topic].advance(
            message, state or {'command': 'MAIN_MENU', 'step': 1}, deps)

    def _quick_command(self, message, deps):
        lowered = message.lower()
        for prefix in self._quick_prefixes:
            if lowered.startswith(prefix):
                flow, method = self._quick[prefix]
                return getattr(flow, method)(message, deps)
        return None

    # --- enacting a FlowResult -------------------------------------------

    def _enact(self, node, result, deps):
        outbound = [(node, reply) for reply in result.replies]
        outbound += list(result.notifications)
        return outbound + self._apply(node, result.outcome, deps)

    def _apply(self, node, outcome, deps):
        """Enact one outcome: update this node's state, and for a hand-off,
        return the menu-or-opening's replies. Nothing else may be set — the
        outcome is a single value, so the old flag combinations can't occur."""
        if isinstance(outcome, Keep):
            return []
        if isinstance(outcome, End):
            self._states[node] = None
            return []
        if isinstance(outcome, Stay):
            self._states[node] = outcome.state
            return []
        if isinstance(outcome, Goto):
            handed_off = self._navigation.show(outcome.menu, deps)
        elif isinstance(outcome, Enter):
            handed_off = self._flows[outcome.topic].entry(deps)
        else:
            raise TypeError(f"unknown flow outcome: {outcome!r}")
        replies = [(node, reply) for reply in handed_off.replies]
        return replies + self._apply(node, handed_off.outcome, deps)
