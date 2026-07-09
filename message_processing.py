import logging

from command_handlers import (
    handle_mail_command, handle_bulletin_command, handle_help_command, handle_stats_command, handle_fortune_command,
    handle_wall_of_shame_command,
    handle_channel_directory_command, handle_send_mail_command,
    handle_check_mail_command, handle_post_bulletin_command,
    handle_check_bulletin_command, handle_read_bulletin_command,
    handle_post_channel_command, handle_list_channels_command, handle_quick_help_command
)
from js8call_integration import handle_js8call_command, handle_js8call_steps, handle_group_message_selection
from utils import get_user_state, get_node_short_name, get_node_id_from_num, send_message, update_user_state
from session import Session
from flows.base import Deps, GOTO_MAIN, GOTO_BBS, GOTO_UTILITIES
from adapters import Store, Lookup
from events import Origin
import replication

# Deep dispatcher for migrated conversation topics. Topics not yet registered
# fall through to the legacy handle_*_steps path below.
_SESSION = Session()

# Menu the router shows when a flow hands the conversation back. Resolved
# against the legacy help command until NavigationFlow owns menus.
_GOTO_MENU = {GOTO_MAIN: None, GOTO_BBS: "bbs", GOTO_UTILITIES: "utilities"}


def _dispatch_session(sender_id, command, message, state, interface):
    """Run one step of a migrated flow and enact its result at the seam.

    The flow is pure — it returns replies and where to go next. Sending, state
    storage, and the menu hand-off happen here, not inside the flow.
    """
    deps = Deps(
        roster=interface.nodes,
        store=Store(interface),
        lookup=Lookup(interface),
        node_num=sender_id,
        node_id=get_node_id_from_num(sender_id, interface),
        allowed_nodes=getattr(interface, "allowed_nodes", []),
    )
    result = _SESSION.advance(command, message, state, deps)
    for reply in result.replies:
        send_message(reply, sender_id, interface)
    for destination, text in result.notifications:
        send_message(text, destination, interface)
    if result.goto is not None:
        handle_help_command(sender_id, interface, _GOTO_MENU[result.goto])
    else:
        update_user_state(sender_id, result.next_state)

main_menu_handlers = {
    "q": handle_quick_help_command,
    "b": lambda sender_id, interface: handle_help_command(sender_id, interface, 'bbs'),
    "u": lambda sender_id, interface: handle_help_command(sender_id, interface, 'utilities'),
    "x": handle_help_command
}

bbs_menu_handlers = {
    "m": handle_mail_command,
    "b": handle_bulletin_command,
    "c": handle_channel_directory_command,
    "j": handle_js8call_command,
    "x": handle_help_command
}


utilities_menu_handlers = {
    "s": handle_stats_command,
    "f": handle_fortune_command,
    "w": handle_wall_of_shame_command,
    "x": handle_help_command
}


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
    else:
        if message_lower.startswith("sm,,"):
            handle_send_mail_command(sender_id, message_strip, interface, bbs_nodes)
        elif message_lower.startswith("cm"):
            handle_check_mail_command(sender_id, interface)
        elif message_lower.startswith("pb,,"):
            handle_post_bulletin_command(sender_id, message_strip, interface, bbs_nodes)
        elif message_lower.startswith("cb,,"):
            handle_check_bulletin_command(sender_id, message_strip, interface)
        elif message_lower.startswith("chp,,"):
            handle_post_channel_command(sender_id, message_strip, interface)
        elif message_lower.startswith("chl"):
            handle_list_channels_command(sender_id, interface)
        else:
            if state and state['command'] == 'MENU':
                menu_name = state['menu']
                if menu_name == 'bbs':
                    handlers = bbs_menu_handlers
                elif menu_name == 'utilities':
                    handlers = utilities_menu_handlers
                else:
                    handlers = main_menu_handlers
            elif state and state['command'] == 'JS8CALL_MENU':
                handle_js8call_steps(sender_id, message, state['step'], interface, state)
                return
            elif state and state['command'] == 'GROUP_MESSAGES':
                handle_group_message_selection(sender_id, message, state['step'], state, interface)
                return
            else:
                handlers = main_menu_handlers

            if message_lower == 'x':
                # Reset to main menu state
                handle_help_command(sender_id, interface)
                return

            # Migrated topics are owned entirely by the Session seam, across
            # both the menu-dict and stepped dispatch paths below.
            if state and _SESSION.handles(state['command']):
                _dispatch_session(sender_id, state['command'], message, state, interface)
                return

            if message_lower in handlers:
                handlers[message_lower](sender_id, interface)
            elif state:
                command = state['command']
                step = state['step']

                # Mail, Bulletins, Stats and Channels are owned by the Session seam
                # (handled above). What remains here is not yet migrated.
                if command == 'CHECK_BULLETIN':
                    if step == 1:
                        handle_read_bulletin_command(sender_id, message, state, interface)
                elif command == 'JS8CALL_MENU':
                    handle_js8call_steps(sender_id, message, step, interface, state)
                elif command == 'GROUP_MESSAGES':
                    handle_group_message_selection(sender_id, message, step, state, interface)
                else:
                    handle_help_command(sender_id, interface)
            else:
                handle_help_command(sender_id, interface)


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
