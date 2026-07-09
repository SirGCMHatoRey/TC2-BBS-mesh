"""Unit tests for Replication — the sync/broadcast decision and wire format.

No database. A fake interface records what would go out over the mesh.
"""

import types

import utils
import replication
from events import (
    BulletinDeleted, BulletinPosted, ChannelAdded, MailDeleted, MailSent, Origin,
)
from replication import Replication, decode, encode, is_sync_message

utils.time.sleep = lambda *a, **k: None

BROADCAST = 4294967295


class FakeInterface:
    def __init__(self, bbs_nodes=None):
        self.bbs_nodes = bbs_nodes or []
        self.nodes = {}
        self.outbox = []
        self._n = 0

    def sendText(self, text, destinationId, wantAck=True, wantResponse=False):
        self.outbox.append((destinationId, text))
        self._n += 1
        return types.SimpleNamespace(id=self._n)


URGENT = BulletinPosted("Urgent", "AA", "Flood", "Move now", "u1")
GENERAL = BulletinPosted("General", "AA", "Hello", "Body", "u2")
MAIL = MailSent("!me", "ME", "!bob", "Subj", "Body", "u3")


def sent_to(interface, dest):
    return [t for d, t in interface.outbox if d == dest]


def broadcasts(interface):
    return sent_to(interface, BROADCAST)


# --- wire format -----------------------------------------------------------

def test_round_trip_bulletin():
    assert decode(encode(URGENT)) == URGENT


def test_round_trip_mail():
    assert decode(encode(MAIL)) == MAIL


def test_round_trip_deletes_and_channel():
    for event in (BulletinDeleted("u9"), MailDeleted("u8"), ChannelAdded("Net", "url")):
        assert decode(encode(event)) == event


def test_encode_bulletin_wire_format_is_stable():
    # Peers on the old code must still understand us.
    assert encode(URGENT) == "BULLETIN|Urgent|AA|Flood|Move now|u1"


def test_encode_mail_wire_format_is_stable():
    assert encode(MAIL) == "MAIL|!me|ME|!bob|Subj|Body|u3"


def test_decode_rejects_conversation():
    assert decode("hello there") is None
    assert decode("b") is None


def test_decode_malformed_returns_none():
    assert decode("BULLETIN|Urgent|AA") is None


def test_is_sync_message_recognizes_prefixes():
    assert is_sync_message("BULLETIN|x")
    assert is_sync_message("MAIL|x")
    assert is_sync_message("DELETE_BULLETIN|x")
    assert is_sync_message("DELETE_MAIL|x")


def test_is_sync_message_excludes_channel_and_conversation():
    # CHANNEL| is decodable but not treated as sync on arrival (existing behaviour).
    assert not is_sync_message("CHANNEL|Net|url")
    assert not is_sync_message("hello")


# --- sync decision ---------------------------------------------------------

def test_local_record_is_synced_to_peers():
    i = FakeInterface(bbs_nodes=["!p1", "!p2"])
    Replication(i).publish(GENERAL, Origin.LOCAL)
    assert sent_to(i, "!p1") == [encode(GENERAL)]
    assert sent_to(i, "!p2") == [encode(GENERAL)]


def test_synced_record_is_not_echoed_back():
    i = FakeInterface(bbs_nodes=["!p1"])
    Replication(i).publish(GENERAL, Origin.SYNCED)
    assert sent_to(i, "!p1") == []


def test_no_peers_means_no_sync():
    i = FakeInterface(bbs_nodes=[])
    Replication(i).publish(GENERAL, Origin.LOCAL)
    assert i.outbox == []


# --- broadcast decision ----------------------------------------------------

def test_urgent_bulletin_broadcasts_when_local():
    i = FakeInterface()
    Replication(i).publish(URGENT, Origin.LOCAL)
    assert len(broadcasts(i)) == 1
    assert "NEW URGENT BULLETIN" in broadcasts(i)[0]
    assert "Flood" in broadcasts(i)[0]


def test_urgent_bulletin_broadcasts_exactly_once_when_synced():
    i = FakeInterface()
    Replication(i).publish(URGENT, Origin.SYNCED)
    assert len(broadcasts(i)) == 1


def test_non_urgent_bulletin_never_broadcasts():
    i = FakeInterface()
    Replication(i).publish(GENERAL, Origin.LOCAL)
    assert broadcasts(i) == []


def test_mail_never_broadcasts():
    i = FakeInterface()
    Replication(i).publish(MAIL, Origin.LOCAL)
    assert broadcasts(i) == []


def test_broadcast_is_driven_by_board_policy_not_the_name():
    # An unknown board neither broadcasts nor raises.
    i = FakeInterface()
    Replication(i).publish(BulletinPosted("Sports", "AA", "x", "y", "u"), Origin.LOCAL)
    assert broadcasts(i) == []


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"ok  {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {fn.__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
