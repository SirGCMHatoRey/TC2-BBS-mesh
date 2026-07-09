"""Tests for the Transport seam: chunking, pacing, and failure handling."""

import os
import sys

# Run from anywhere: put the repo root on the path before importing the modules
# under test. Keeps `python tests/test_x.py` working alongside pytest.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
import types

import transport
from transport import MAX_PAYLOAD, MeshtasticTransport, chunks


class FakeInterface:
    """Stands in for the meshtastic interface. Only Transport ever sees one."""

    def __init__(self, nodes=None, my_num=7, fail_with=None):
        self.nodes = nodes or {}
        self.myInfo = types.SimpleNamespace(my_node_num=my_num)
        self.sent = []
        self.closed = False
        self._fail_with = fail_with
        self._packet_id = 0

    def sendText(self, text, destinationId, wantAck=True, wantResponse=False):
        if self._fail_with is not None:
            raise self._fail_with
        self.sent.append((destinationId, text))
        self._packet_id += 1
        return types.SimpleNamespace(id=self._packet_id)

    def close(self):
        self.closed = True


def no_pacing(interface):
    return MeshtasticTransport(interface, pacing_seconds=0)


# --- chunking (pure) -------------------------------------------------------

def test_short_text_is_one_chunk():
    assert chunks("hello") == ["hello"]


def test_long_text_is_split_at_the_payload_limit():
    text = "x" * (MAX_PAYLOAD + 5)
    pieces = chunks(text)
    assert len(pieces) == 2
    assert len(pieces[0]) == MAX_PAYLOAD
    assert len(pieces[1]) == 5
    assert "".join(pieces) == text


def test_empty_text_sends_nothing():
    assert chunks("") == []


# --- sending ---------------------------------------------------------------

def test_send_delivers_one_chunk():
    interface = FakeInterface()
    no_pacing(interface).send("hello", 42)
    assert interface.sent == [(42, "hello")]


def test_send_splits_a_long_reply():
    interface = FakeInterface()
    no_pacing(interface).send("y" * (MAX_PAYLOAD + 1), 42)
    assert len(interface.sent) == 2
    assert interface.sent[0][0] == 42


def test_send_paces_between_chunks():
    interface = FakeInterface()
    slept = []
    original = transport.time.sleep
    transport.time.sleep = lambda seconds: slept.append(seconds)
    try:
        MeshtasticTransport(interface, pacing_seconds=2).send("z" * (MAX_PAYLOAD + 1), 42)
    finally:
        transport.time.sleep = original
    assert slept == [2, 2]


def test_a_failed_send_is_logged_not_raised():
    """The old handler read `e.message`, raising AttributeError from the except."""
    interface = FakeInterface(fail_with=OSError("radio busy"))
    no_pacing(interface).send("hello", 42)      # must not raise
    assert interface.sent == []


def test_a_failed_chunk_does_not_stop_the_rest():
    interface = FakeInterface(fail_with=OSError("radio busy"))
    logging.disable(logging.CRITICAL)
    try:
        no_pacing(interface).send("q" * (MAX_PAYLOAD + 1), 42)
    finally:
        logging.disable(logging.NOTSET)
    assert interface.sent == []                 # both failed, neither raised


# --- the rest of the seam --------------------------------------------------

def test_nodes_are_read_live_from_the_interface():
    interface = FakeInterface(nodes={"!a": {"num": 1}})
    t = no_pacing(interface)
    assert t.nodes == {"!a": {"num": 1}}
    interface.nodes["!b"] = {"num": 2}
    assert "!b" in t.nodes


def test_my_num_comes_from_my_info():
    assert no_pacing(FakeInterface(my_num=1234)).my_num == 1234


def test_close_closes_the_interface():
    interface = FakeInterface()
    no_pacing(interface).close()
    assert interface.closed


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
