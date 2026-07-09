"""The router: decides whether an inbound message is replication or conversation,
hands conversation to the Session, and does the sending.

Every dispatch decision now lives behind the Session seam. Nothing stepped
remains here.
"""

import logging

from utils import get_user_state, get_node_short_name, get_node_id_from_num, send_message, update_user_state
from session import Session
from flows.base import Deps, GOTO_MAIN
from adapters import Store, Lookup
from events import Origin
import replication
import settings

_SESSION = Session()


def _build_deps(sender_id, interface):
    return Deps(
        roster=interface.nodes,
        store=Store(interface),
        lookup=Lookup(interface),
        node_num=sender_id,
        node_id=get_node_id_from_num(sender_id, interface),
        allowed_nodes=getattr(interface, "allowed_nodes", []),
        js8=settings.js8_database(),
        menus=settings.menus(),
        fortunes=settings.fortunes(),
    )


def _enact(sender_id, result, deps, interface):
    """Send what a flow produced and store where the conversation now stands.

    A flow returns replies plus at most one hand-off: `goto` asks for a menu,
    `enter` hands the conversation to another flow. Both are resolved through
    the Session, so menus and openings each have exactly one owner.
    """
    for reply in result.replies:
        send_message(reply, sender_id, interface)
    for destination, text in result.notifications:
        send_message(text, destination, interface)

    if result.goto is not None:
        handed_off = _SESSION.show(result.goto, deps)
    elif result.enter is not None:
        handed_off = _SESSION.enter(result.enter, deps)
    else:
        if not result.keep_state:
            update_user_state(sender_id, result.next_state)
        return

    for reply in handed_off.replies:
        send_message(reply, sender_id, interface)
    update_user_state(sender_id, handed_off.next_state)


def process_message(sender_id, message, interface, is_sync_message=False):
    if is_sync_message:
        # A record from a peer: store it, then let Replication decide whether
        # the mesh needs to hear about it. It is never echoed back to peers.
        event = replication.decode(message)
        if event is None:
            logging.error(f"Unrecognized sync message: {message!r}")
            return
        Store(interface).accept(event)
        replication.Replication(interface).publish(event, Origin.SYNCED)
        return

    state = get_user_state(sender_id)
    message_strip = message.strip()
    message_lower = message_strip.lower()

    # Handle repeated characters for single character commands using a prefix
    if len(message_lower) == 2 and message_lower[1] == 'x':
        message_lower = message_lower[0]

    deps = _build_deps(sender_id, interface)

    # Quick commands act from anywhere, without moving the conversation.
    result = _SESSION.quick(message_strip, deps)
    if result is not None:
        _enact(sender_id, result, deps, interface)
        return

    # EXIT from anywhere returns to the main menu, before any flow sees it.
    if message_lower == 'x':
        _enact(sender_id, _SESSION.show(GOTO_MAIN, deps), deps, interface)
        return

    # No state means the conversation is sitting at the main menu.
    topic = state['command'] if state else 'MAIN_MENU'
    if not _SESSION.handles(topic):
        _enact(sender_id, _SESSION.show(GOTO_MAIN, deps), deps, interface)
        return

    result = _SESSION.advance(topic, message, state or {'command': 'MAIN_MENU', 'step': 1}, deps)
    _enact(sender_id, result, deps, interface)


def on_receive(packet, interface):
    try:
        if 'decoded' in packet and packet['decoded']['portnum'] == 'TEXT_MESSAGE_APP':
            message_bytes = packet['decoded']['payload']
            message_string = message_bytes.decode('utf-8')
            sender_id = packet['from']
            to_id = packet.get('to')
            sender_node_id = packet['fromId']

            sender_short_name = get_node_short_name(sender_node_id, interface)
            receiver_short_name = get_node_short_name(get_node_id_from_num(to_id, interface),
                                                      interface) if to_id else "Group Chat"
            logging.info(f"Received message from user '{sender_short_name}' ({sender_node_id}) to {receiver_short_name}: {message_string}")

            bbs_nodes = interface.bbs_nodes
            is_sync_message = replication.is_sync_message(message_string)

            if sender_node_id in bbs_nodes:
                if is_sync_message:
                    process_message(sender_id, message_string, interface, is_sync_message=True)
                else:
                    logging.info("Ignoring non-sync message from known BBS node")
            elif to_id is not None and to_id != 0 and to_id != 255 and to_id == interface.myInfo.my_node_num:
                process_message(sender_id, message_string, interface, is_sync_message=False)
            else:
                logging.info("Ignoring message sent to group chat or from unknown node")
    except KeyError as e:
        logging.error(f"Error processing packet: {e}")
