"""Adapters binding the live meshtastic interface to the small collaborators
flows depend on.

These are where candidate 02 (persistence/sync split) and candidate 01
(transport/lookup seam) will eventually crystallize. For now ``Store`` is a
thin binding over ``db_operations`` that carries the interface and peer list
so a flow can persist without knowing about either — the flow sees only the
methods it needs, not the radio.
"""

import db_operations


class Store:
    """Persistence for a flow, with the interface + peer list bound in.

    A flow calls ``store.add_bulletin(board, name, subject, content)`` and the
    store handles the write, the peer sync, and (for urgent) the broadcast —
    all side effects candidate 02 will later lift into a Replication module.
    """

    def __init__(self, interface):
        self._interface = interface

    def get_bulletins(self, board):
        return db_operations.get_bulletins(board)

    def get_bulletin_content(self, bulletin_id):
        return db_operations.get_bulletin_content(bulletin_id)

    def add_bulletin(self, board, sender_short_name, subject, content):
        return db_operations.add_bulletin(
            board, sender_short_name, subject, content,
            self._interface.bbs_nodes, self._interface)
