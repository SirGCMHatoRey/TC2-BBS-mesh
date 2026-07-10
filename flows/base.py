"""Shared shapes for conversation flows.

A Flow is a deep module owning one conversation topic (mail, bulletins,
stats, ...). It is *pure*: ``advance(message, state, deps)`` computes what to
say and where the conversation goes next, and returns it — it never sends
messages, touches the radio, or reaches for a global. The router at the seam
does the sending; the collaborators a flow needs are handed in via ``Deps``.

This keeps the interface the test surface: feed a flow a message + state,
assert on the returned replies and next state, no mocking of transport.
"""

from dataclasses import dataclass, field
from typing import Any, List, Optional


@dataclass
class Deps:
    """Collaborators handed to a flow so it stays pure.

    Built fresh at the router edge from the live interface. Grows as flows
    migrate: ``roster`` for stats, ``store`` for persistence (candidate 02's
    seam showing up early), and the acting-node context a flow needs to make
    permission decisions without touching the interface itself.
    """

    roster: dict = field(default_factory=dict)   # node_id -> node dict (interface.nodes)
    store: Any = None                            # persistence adapter (candidate 02 seam)
    lookup: Any = None                           # node-resolution adapter (candidate 01 seam)
    node_id: Any = None                          # acting node's id, resolved from the roster
    allowed_nodes: List[str] = field(default_factory=list)   # urgent-board allow-list
    js8: Any = None                              # Js8Database — what the JS8Call bridge heard
    menus: Any = None                            # settings.Menus — which letters each menu offers
    fortunes: List[str] = field(default_factory=list)


#: A Node absent from the roster, or without a short name, cannot be named as
#: the author of anything. Authorship is stored on the record and travels to
#: peers on the wire, so the write is refused rather than attributed to nobody.
UNKNOWN_NODE_REPLY = "Error: Unable to retrieve your node information."


# Menu hand-off targets. A flow names where the conversation should return to;
# the router resolves it (against legacy help today, NavigationFlow later).
GOTO_MAIN = "main"
GOTO_BBS = "bbs"
GOTO_UTILITIES = "utilities"


@dataclass
class FlowResult:
    """What a flow hands back to the router.

    replies: text chunks to send to the current node, in order.
    next_state: the state dict to store for this node (None ends the flow).
    goto: request a menu be shown after the replies — one of GOTO_*. A
        placeholder for the cross-flow hand-off NavigationFlow will own; until
        then the router resolves it against the legacy help command. When set,
        it supersedes next_state (the menu owns the new state).
    """

    replies: List[str] = field(default_factory=list)
    next_state: Optional[dict] = None
    goto: Optional[str] = None
    #: Hand the conversation to another Flow, named by one of its topics. The
    #: router asks that Flow for its entry — its greeting and starting state —
    #: so each Flow owns its own opening rather than Navigation knowing them all.
    enter: Optional[str] = None
    #: Leave the conversation exactly where it was. Quick commands act without
    #: moving you: sending SM,, mid-compose sends the mail and leaves you in
    #: the compose step, as it always has.
    keep_state: bool = False
    #: Out-of-band messages to nodes other than the sender, as (destination,
    #: text) pairs — e.g. the "you have new mail" nudge to a recipient. The
    #: router sends these after the replies. This is the cross-node messaging
    #: that the Transport seam (candidate 01) will eventually own.
    notifications: List[tuple] = field(default_factory=list)
