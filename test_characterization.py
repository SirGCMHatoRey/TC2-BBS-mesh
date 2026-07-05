"""Characterization tests for the current conversation behaviour.

These lock the observable behaviour of the BBS *before* the Session/flows
refactor, so the migration can be proven behaviour-preserving.

They drive the real ``message_processing.process_message`` through a fake
meshtastic interface and capture what the BBS sends back. The harness's
``Session.advance(message) -> [replies]`` is deliberately shaped like the
future ``session.advance(node, message)`` seam: when the real Session lands,
it drops in behind this same contract and these tests should stay green.

Pure and fast — no radio, no real database, no 2-second pacing. Runs under
pytest, or standalone (``python test_characterization.py``).
"""

import contextlib
import io
import os
import shutil
import sqlite3
import types

# command_handlers reads config.ini at import time, so it must exist first.
if not os.path.exists("config.ini"):
    shutil.copy("example_config.ini", "config.ini")

import utils
import db_operations
import message_processing

# The real send_message sleeps 2s per chunk to pace the radio. Neutralize it
# or the suite is unusably slow; characterization runs at the message seam.
utils.time.sleep = lambda *a, **k: None


# --------------------------------------------------------------------------
# Fake interface + harness
# --------------------------------------------------------------------------

class _Sent:
    """Stand-in for the packet meshtastic returns from sendText."""

    def __init__(self, packet_id):
        self.id = packet_id


class FakeInterface:
    """Records outbound text instead of transmitting it."""

    def __init__(self, nodes, my_num, allowed_nodes=None, bbs_nodes=None):
        self.nodes = nodes
        self.myInfo = types.SimpleNamespace(my_node_num=my_num)
        self.allowed_nodes = allowed_nodes or []
        self.bbs_nodes = bbs_nodes or []
        self.outbox = []          # list of (destination_num, text)
        self._packet_id = 0

    def sendText(self, text, destinationId, wantAck=True, wantResponse=False):
        self.outbox.append((destinationId, text))
        self._packet_id += 1
        return _Sent(self._packet_id)


def make_node(num, short, long_name, hw="TBEAM", role="CLIENT",
              last_heard=None, battery=80):
    return {
        "num": num,
        "user": {"shortName": short, "longName": long_name,
                 "hwModel": hw, "role": role},
        "lastHeard": last_heard,
        "deviceMetrics": {"batteryLevel": battery},
    }


class Session:
    """Thin shim over process_message, shaped like the future Session seam."""

    def __init__(self, interface, node_num):
        self.interface = interface
        self.node = node_num

    def advance(self, message):
        """Feed one inbound message, return the replies sent to this node."""
        self.interface.outbox.clear()
        message_processing.process_message(self.node, message, self.interface)
        return [text for dest, text in self.interface.outbox if dest == self.node]

    def broadcasts(self):
        """Text sent to anywhere other than this node (e.g. mesh broadcast)."""
        return [text for dest, text in self.interface.outbox if dest != self.node]


SENDER_NUM = 1001
SENDER_ID = "!sender"


def new_session(allowed_nodes=None, extra_nodes=None):
    """Fresh conversation: cleared state + in-memory database."""
    utils.user_states.clear()

    conn = sqlite3.connect(":memory:", check_same_thread=False)
    db_operations.get_db_connection = lambda: conn
    message_processing.get_db_connection = lambda: conn
    with contextlib.redirect_stdout(io.StringIO()):
        db_operations.initialize_database()

    nodes = {SENDER_ID: make_node(SENDER_NUM, "SEND", "Sender Node")}
    if extra_nodes:
        nodes.update(extra_nodes)
    interface = FakeInterface(nodes, my_num=9999, allowed_nodes=allowed_nodes)
    return Session(interface, SENDER_NUM)


def joined(replies):
    return "\n".join(replies)


# --------------------------------------------------------------------------
# Navigation
# --------------------------------------------------------------------------

def test_unknown_message_shows_main_menu():
    s = new_session()
    r = joined(s.advance("hello"))
    assert "💾TC² BBS💾" in r
    assert "[B]BS" in r


def test_main_menu_shows_empty_mail_count():
    s = new_session()
    r = joined(s.advance("hello"))
    assert "✉️:0" in r


def test_enter_bbs_menu():
    s = new_session()
    r = joined(s.advance("b"))
    assert "📰BBS Menu📰" in r
    assert "[M]ail" in r


def test_enter_utilities_menu():
    s = new_session()
    r = joined(s.advance("u"))
    assert "🛠️Utilities Menu🛠️" in r


# --------------------------------------------------------------------------
# Mail
# --------------------------------------------------------------------------

def test_mail_menu_then_read_empty_inbox():
    s = new_session()
    s.advance("b")
    r = joined(s.advance("m"))
    assert "✉️Mail Menu✉️" in r

    r = joined(s.advance("r"))
    assert "no messages in your mailbox" in r


def test_mail_send_to_unknown_short_name():
    s = new_session()
    s.advance("b")
    s.advance("m")
    r = joined(s.advance("s"))
    assert "Short Name" in r

    r = joined(s.advance("zzz"))
    assert "unable to find that node" in r


def test_quick_send_mail_rejects_bad_format():
    s = new_session()
    r = joined(s.advance("sm,,foo"))
    assert "Send Mail Quick Command format" in r


def test_send_mail_end_to_end_persists_and_notifies():
    s = new_session(extra_nodes={"!bob": make_node(2002, "BOB", "Bob Node")})
    s.advance("b")            # bbs menu
    s.advance("m")            # mail menu
    s.advance("s")            # send
    r = joined(s.advance("bob"))          # resolve recipient
    assert "message to Bob Node" in r

    s.advance("Greetings")    # subject
    s.advance("Body line")    # content
    r = joined(s.advance("END"))
    assert "posted to the mailbox of Bob Node" in r

    # Recipient gets the out-of-band nudge, and the mail is stored for them.
    assert "new mail message from SEND" in joined(s.broadcasts())
    assert len(db_operations.get_mail("!bob")) == 1


# --------------------------------------------------------------------------
# Stats
# --------------------------------------------------------------------------

def test_stats_node_count():
    s = new_session()
    s.advance("u")
    r = joined(s.advance("s"))
    assert "📊Stats Menu📊" in r

    r = joined(s.advance("n"))
    assert "Total nodes seen:" in r
    assert "All time: 1" in r


# --------------------------------------------------------------------------
# Bulletins (these exercise Board's territory)
# --------------------------------------------------------------------------

def test_quick_check_bulletin_empty_board():
    s = new_session()
    r = joined(s.advance("cb,,General"))
    assert "No bulletins available on General board" in r


def test_post_bulletin_to_general_persists():
    s = new_session()
    s.advance("b")            # bbs menu
    s.advance("b")            # bulletin menu
    r = joined(s.advance("g"))            # General board
    assert "General has 0 messages" in r

    assert "subject" in joined(s.advance("p")).lower()
    assert "contents" in joined(s.advance("My Subject")).lower()
    s.advance("Body line one")            # accumulates, no reply
    r = joined(s.advance("END"))
    assert "posted to General" in r

    assert len(db_operations.get_bulletins("General")) == 1


def test_urgent_post_denied_without_permission():
    s = new_session(allowed_nodes=["!someone_else"])
    s.advance("b")            # bbs menu
    s.advance("b")            # bulletin menu
    r = joined(s.advance("u"))            # Urgent board
    assert "Urgent has 0 messages" in r

    r = joined(s.advance("p"))
    assert "don't have permission" in r


def test_urgent_post_allowed_broadcasts():
    s = new_session(allowed_nodes=[SENDER_ID])
    s.advance("b")
    s.advance("b")
    s.advance("u")
    s.advance("p")            # permitted
    s.advance("Flash Flood")  # subject
    s.advance("Move to high ground")  # content
    s.advance("END")          # posts + broadcasts

    broadcast = joined(s.broadcasts())
    assert "NEW URGENT BULLETIN" in broadcast
    assert len(db_operations.get_bulletins("Urgent")) == 1


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
