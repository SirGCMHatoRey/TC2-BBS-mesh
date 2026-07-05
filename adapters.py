"""Adapters binding the live meshtastic interface to the small collaborators
flows depend on.

These are where candidate 02 (persistence/sync split) and candidate 01
(transport/lookup seam) will eventually crystallize. For now ``Store`` is a
thin binding over ``db_operations`` that carries the interface and peer list
so a flow can persist without knowing about either — the flow sees only the
methods it needs, not the radio.
"""

import db_operations
import utils


class Store:
    """Persistence for a flow, with the interface + peer list bound in.

    A flow calls e.g. ``store.add_bulletin(board, name, subject, content)`` and
    the store handles the write, the peer sync, and (for urgent) the broadcast
    — the side effects candidate 02 will later lift into a Replication module.
    """

    def __init__(self, interface):
        self._interface = interface

    # bulletins ------------------------------------------------------------
    def get_bulletins(self, board):
        return db_operations.get_bulletins(board)

    def get_bulletin_content(self, bulletin_id):
        return db_operations.get_bulletin_content(bulletin_id)

    def add_bulletin(self, board, sender_short_name, subject, content):
        return db_operations.add_bulletin(
            board, sender_short_name, subject, content,
            self._interface.bbs_nodes, self._interface)

    # mail -----------------------------------------------------------------
    def get_mail(self, recipient_id):
        return db_operations.get_mail(recipient_id)

    def get_mail_content(self, mail_id, recipient_id):
        return db_operations.get_mail_content(mail_id, recipient_id)

    def add_mail(self, sender_id, sender_short_name, recipient_id, subject, content):
        return db_operations.add_mail(
            sender_id, sender_short_name, recipient_id, subject, content,
            self._interface.bbs_nodes, self._interface)

    def delete_mail(self, unique_id, recipient_id):
        return db_operations.delete_mail(
            unique_id, recipient_id, self._interface.bbs_nodes, self._interface)

    def sender_id_by_mail_id(self, mail_id):
        return db_operations.get_sender_id_by_mail_id(mail_id)


class Lookup:
    """Node resolution for a flow — the seam candidate 01 will formalize.

    Wraps the node-map reads scattered through utils/command_handlers so a
    flow can resolve short names and display names without holding the radio.
    """

    def __init__(self, interface):
        self._interface = interface

    def node_info(self, short_name):
        """Nodes matching a short name; each entry's 'num' is its node id."""
        return utils.get_node_info(self._interface, short_name)

    def node_name(self, node_id):
        """Long display name for a node id, or a 'Node <id>' fallback."""
        info = self._interface.nodes.get(node_id)
        if info:
            return info["user"]["longName"]
        return f"Node {node_id}"

    def short_name(self, node_id):
        """Short name for a node id, or None if unknown."""
        return utils.get_node_short_name(node_id, self._interface)
