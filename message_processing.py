"""The router: decides whether an inbound message is replication or conversation,
hands conversation to the Session, and does the sending.

It talks to a Transport, never to the meshtastic interface. `on_receive` is the
one place that wraps the interface pubsub hands us.
"""

import logging

from utils import get_user_state, update_user_state
from session import Session
from flows.base import Deps, GOTO_MAIN
from adapters import Store, Lookup
from events import Origin
from replication import Replication
from transport import MeshtasticTransport
import replication
import roster
import settings

_SESSION = Session()


def _build_deps(sender_id, transport):
    nodes = transport.nodes
    lookup = Lookup(nodes)
    store = Store(Replication(transport, settings.bbs_nodes()))
    return Deps(
        roster=nodes,
        store=store,
        lookup=lookup,
        node_num=sender_id,
        node_id=lookup.id_from_num(sender_id),
        allowed_nodes=settings.allowed_nodes(),
        js8=settings.js8_database(),
        menus=settings.menus(),
        fortunes=settings.fortunes(),
    )


def _enact(sender_id, result, deps, transport):
    """Send what a flow produced and store where the conversation now stands.

    A flow returns replies plus at most one hand-off: `goto` asks for a menu,
    `enter` hands the conversation to another flow. Both are resolved through
    the Session, so menus and openings each have exactly one owner.
    """
    for reply in result.replies:
        transport.send(reply, sender_id)
    for destination, text in result.notifications:
        transport.send(text, destination)

    if result.goto is not None:
        handed_off = _SESSION.show(result.goto, deps)
    elif result.enter is not None:
        handed_off = _SESSION.enter(result.enter, deps)
    else:
        if not result.keep_state:
            update_user_state(sender_id, result.next_state)
        return

    for reply in handed_off.replies:
        transport.send(reply, sender_id)
    update_user_state(sender_id, handed_off.next_state)


def process_message(sender_id, message, transport, is_sync_message=False):
    if is_sync_message:
        # A record from a peer: store it, then let Replication decide whether
        # the mesh needs to hear about it. It is never echoed back to peers.
        event = replication.decode(message)
        if event is None:
            logging.error(f"Unrecognized sync message: {message!r}")
            return
        peers = settings.bbs_nodes()
        Store(Replication(transport, peers)).accept(event)
        Replication(transport, peers).publish(event, Origin.SYNCED)
        return

    state = get_user_state(sender_id)
    message_strip = message.strip()
    message_lower = message_strip.lower()

    # Handle repeated characters for single character commands using a prefix
    if len(message_lower) == 2 and message_lower[1] == 'x':
        message_lower = message_lower[0]

    deps = _build_deps(sender_id, transport)

    # Quick commands act from anywhere, without moving the conversation.
    result = _SESSION.quick(message_strip, deps)
    if result is not None:
        _enact(sender_id, result, deps, transport)
        return

    # EXIT from anywhere returns to the main menu, before any flow sees it.
    if message_lower == 'x':
        _enact(sender_id, _SESSION.show(GOTO_MAIN, deps), deps, transport)
        return

    # No state means the conversation is sitting at the main menu.
    topic = state['command'] if state else 'MAIN_MENU'
    if not _SESSION.handles(topic):
        _enact(sender_id, _SESSION.show(GOTO_MAIN, deps), deps, transport)
        return

    result = _SESSION.advance(topic, message, state or {'command': 'MAIN_MENU', 'step': 1}, deps)
    _enact(sender_id, result, deps, transport)


def on_receive(packet, interface):
    """The one place that meets the meshtastic interface and wraps it."""
    try:
        if 'decoded' in packet and packet['decoded']['portnum'] == 'TEXT_MESSAGE_APP':
            message_bytes = packet['decoded']['payload']
            message_string = message_bytes.decode('utf-8')
            sender_id = packet['from']
            to_id = packet.get('to')
            sender_node_id = packet['fromId']

            transport = MeshtasticTransport(interface)
            nodes = transport.nodes

            sender_short_name = roster.short_name(nodes, sender_node_id)
            receiver_short_name = roster.short_name(nodes, roster.id_from_num(nodes, to_id)) \
                if to_id else "Group Chat"
            logging.info(f"Received message from user '{sender_short_name}' ({sender_node_id}) to {receiver_short_name}: {message_string}")

            is_sync_message = replication.is_sync_message(message_string)

            if sender_node_id in settings.bbs_nodes():
                if is_sync_message:
                    process_message(sender_id, message_string, transport, is_sync_message=True)
                else:
                    logging.info("Ignoring non-sync message from known BBS node")
            elif to_id is not None and to_id != 0 and to_id != 255 and to_id == transport.my_num:
                process_message(sender_id, message_string, transport, is_sync_message=False)
            else:
                logging.info("Ignoring message sent to group chat or from unknown node")
    except KeyError as e:
        logging.error(f"Error processing packet: {e}")
