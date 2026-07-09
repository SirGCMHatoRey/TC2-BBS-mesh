import logging

from command_handlers import (
    handle_send_mail_command, handle_check_mail_command, handle_post_bulletin_command,
    handle_check_bulletin_command, handle_read_bulletin_command,
    handle_post_channel_command, handle_list_channels_command,
)
from utils import get_user_state, get_node_short_name, get_node_id_from_num, send_message, update_user_state
from session import Session
from flows.base import Deps, GOTO_MAIN
from adapters import Store, Lookup
from events import Origin
import replication
import settings

# Deep dispatcher for conversation topics. The CB,, bulletin read is the only
# stepped state still outside a flow.
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
        update_user_state(sender_id, result.next_state)
        return

    for reply in handed_off.replies:
        send_message(reply, sender_id, interface)
    update_user_state(sender_id, handed_off.next_state)


def _show_main_menu(sender_id, interface):
    deps = _build_deps(sender_id, interface)
    _enact(sender_id, _SESSION.show(GOTO_MAIN, deps), deps, interface)


def process_message(sender_id, message, interface, is_sync_message=False):
    state = get_user_state(sender_id)
    message_lower = message.lower().strip()
    message_strip = message.strip()

    bbs_nodes = interface.bbs_nodes

    # Handle repeated characters for single character commands using a prefix
    if len(message_lower) == 2 and message_lower[1] == 'x':
        message_lower = message_lower[0]

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

    if message_lower.startswith("sm,,"):
        handle_send_mail_command(sender_id, message_strip, interface, bbs_nodes)
        return
    if message_lower.startswith("cm"):
        handle_check_mail_command(sender_id, interface)
        return
    if message_lower.startswith("pb,,"):
        handle_post_bulletin_command(sender_id, message_strip, interface, bbs_nodes)
        return
    if message_lower.startswith("cb,,"):
        handle_check_bulletin_command(sender_id, message_strip, interface)
        return
    if message_lower.startswith("chp,,"):
        handle_post_channel_command(sender_id, message_strip, interface)
        return
    if message_lower.startswith("chl"):
        handle_list_channels_command(sender_id, interface)
        return

    # EXIT from anywhere returns to the main menu, before any flow sees it.
    if message_lower == 'x':
        _show_main_menu(sender_id, interface)
        return

    # No state means the conversation is sitting at the main menu.
    topic = state['command'] if state else 'MAIN_MENU'

    if _SESSION.handles(topic):
        deps = _build_deps(sender_id, interface)
        result = _SESSION.advance(topic, message, state or {'command': 'MAIN_MENU', 'step': 1}, deps)
        _enact(sender_id, result, deps, interface)
        return

    # The CB,, bulletin read is the last stepped state outside a flow.
    if topic == 'CHECK_BULLETIN' and state['step'] == 1:
        handle_read_bulletin_command(sender_id, message, state, interface)
    else:
        _show_main_menu(sender_id, interface)


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
