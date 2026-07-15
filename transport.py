"""Transport — the seam under the radio.

Callers say `send(text, destination)`. Splitting a long reply into payload-sized
chunks, pacing them so the mesh keeps up, and logging what went out all happen
behind that. Nobody outside this module holds the meshtastic interface.

Two adapters justify the seam: MeshtasticTransport in production, and the
FakeTransport the tests use — which records instead of transmitting, and does
not sleep.
"""

import logging
import time

import roster

#: Meshtastic will not carry more than this in one text payload.
MAX_PAYLOAD = 200

#: Wait between chunks so a long reply does not swamp the mesh.
PACING_SECONDS = 4


def chunks(text, size=MAX_PAYLOAD):
    """Split a reply into payload-sized pieces. An empty reply sends nothing."""
    return [text[i:i + size] for i in range(0, len(text), size)]


class MeshtasticTransport:
    def __init__(self, interface, pacing_seconds=PACING_SECONDS):
        self._interface = interface
        self._pacing_seconds = pacing_seconds

    @property
    def nodes(self):
        """The live node roster. Meshtastic keeps this up to date for us."""
        return self._interface.nodes

    @property
    def my_num(self):
        return self._interface.myInfo.my_node_num

    def send(self, text, destination):
        for chunk in chunks(text):
            try:
                packet = self._interface.sendText(
                    text=chunk,
                    destinationId=destination,
                    wantAck=True,
                    wantResponse=False,
                )
            except Exception as error:
                # The old handler read `e.message`, which does not exist in
                # Python 3, so a transient send failure raised AttributeError
                # out of the except clause and killed the caller.
                logging.warning(f"Send to {destination} failed: {error}")
            else:
                self._log_sent(chunk, destination, packet)
            time.sleep(self._pacing_seconds)

    def close(self):
        self._interface.close()

    def _log_sent(self, chunk, destination, packet):
        node_id = roster.id_from_num(self.nodes, destination)
        name = roster.short_name(self.nodes, node_id)
        shown = chunk.replace('\n', '\\n')
        logging.info(f"Sending message to user '{name}' ({node_id}) "
                     f"with sendID {packet.id}: \"{shown}\"")
