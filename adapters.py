"""Adapters binding the live meshtastic interface to the collaborators flows need.

``Store`` composes pure persistence with Replication: it writes the record and
hands it to Replication to decide sync and broadcast. Flows see only the small
interface — they never learn that peers or the mesh exist.

``Lookup`` is the node-resolution seam candidate 01 will formalize.
"""

import db_operations
import utils
from events import (
    BulletinDeleted, BulletinPosted, ChannelAdded, MailDeleted, MailSent, Origin,
)
from replication import Replication


class Store:
    def __init__(self, interface, replication=None):
        self._interface = interface
        self._replication = replication or Replication(interface)

    # bulletins ------------------------------------------------------------
    def get_bulletins(self, board):
        return db_operations.get_bulletins(board)

    def get_bulletin_content(self, bulletin_id):
        return db_operations.get_bulletin_content(bulletin_id)

    def add_bulletin(self, board, sender_short_name, subject, content):
        event = db_operations.insert_bulletin(board, sender_short_name, subject, content)
        self._replication.publish(event, Origin.LOCAL)
        return event.unique_id

    # mail -----------------------------------------------------------------
    def get_mail(self, recipient_id):
        return db_operations.get_mail(recipient_id)

    def get_mail_content(self, mail_id, recipient_id):
        return db_operations.get_mail_content(mail_id, recipient_id)

    def add_mail(self, sender_id, sender_short_name, recipient_id, subject, content):
        event = db_operations.insert_mail(sender_id, sender_short_name, recipient_id,
                                          subject, content)
        self._replication.publish(event, Origin.LOCAL)
        return event.unique_id

    def delete_mail(self, unique_id, recipient_id=None):
        event = db_operations.delete_mail(unique_id)
        if event is not None:
            self._replication.publish(event, Origin.LOCAL)

    def sender_id_by_mail_id(self, mail_id):
        return db_operations.get_sender_id_by_mail_id(mail_id)

    # channels -------------------------------------------------------------
    def get_channels(self):
        return db_operations.get_channels()

    def add_channel(self, name, url):
        event = db_operations.insert_channel(name, url)
        self._replication.publish(event, Origin.LOCAL)

    # replication inbound --------------------------------------------------
    def accept(self, event):
        """Persist a record that arrived from a peer BBS Node."""
        if isinstance(event, BulletinPosted):
            db_operations.insert_bulletin(event.board, event.sender_short_name,
                                          event.subject, event.content,
                                          unique_id=event.unique_id)
        elif isinstance(event, MailSent):
            db_operations.insert_mail(event.sender_id, event.sender_short_name,
                                      event.recipient_id, event.subject,
                                      event.content, unique_id=event.unique_id)
        elif isinstance(event, BulletinDeleted):
            db_operations.delete_bulletin(event.unique_id)
        elif isinstance(event, MailDeleted):
            db_operations.delete_mail(event.unique_id)
        elif isinstance(event, ChannelAdded):
            db_operations.insert_channel(event.name, event.url)


class Lookup:
    """Node resolution for a flow — the seam candidate 01 will formalize."""

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
