"""Unit tests for BulletinFlow — pure, with a fake store.

No interface, no database. A fake store stands in for persistence; the flow's
replies and next state are asserted directly. Covers board selection, read,
post, and the urgent permission branch that consumes the Board policy flags.
"""

from flows.base import Deps
from flows.bulletin import BulletinFlow


class FakeStore:
    def __init__(self, bulletins=None, content=None):
        self._bulletins = bulletins or {}     # board name -> list of rows
        self._content = content or {}         # id -> content tuple
        self.added = []                       # recorded add_bulletin calls

    def get_bulletins(self, board):
        return self._bulletins.get(board, [])

    def get_bulletin_content(self, bulletin_id):
        return self._content[bulletin_id]

    def add_bulletin(self, board, sender_short_name, subject, content):
        self.added.append((board, sender_short_name, subject, content))
        return "uid-1"


def deps(store=None, node_id="!me", allowed=None, roster=None):
    return Deps(
        roster=roster if roster is not None else {"!me": {"user": {"shortName": "ME"}}},
        store=store or FakeStore(),
        node_num=1001,
        node_id=node_id,
        allowed_nodes=allowed or [],
    )


def st(command, **extra):
    return {"command": command, **extra}


# --- board selection -------------------------------------------------------

def test_select_board_reports_count_and_advances():
    store = FakeStore(bulletins={"General": [(1, "Hi", "AA", "d", "u")]})
    r = BulletinFlow().advance("g", st("BULLETIN_MENU"), deps(store))
    assert "General has 1 messages" in r.replies[0]
    assert r.next_state == {"command": "BULLETIN_ACTION", "step": 2, "board": "General"}


def test_unknown_board_letter_goes_to_main():
    r = BulletinFlow().advance("z", st("BULLETIN_MENU"), deps())
    assert r.goto == "main"


# --- read ------------------------------------------------------------------

def test_read_empty_board_returns_to_bbs():
    r = BulletinFlow().advance("r", st("BULLETIN_ACTION", board="News"), deps())
    assert r.replies == ["No bulletins in News."]
    assert r.goto == "bbs"


def test_read_lists_bulletins():
    store = FakeStore(bulletins={"Info": [(7, "Subject A", "AA", "d", "u"),
                                          (9, "Subject B", "BB", "d", "u")]})
    r = BulletinFlow().advance("r", st("BULLETIN_ACTION", board="Info"), deps(store))
    assert r.replies[0] == "Select a bulletin number to view from Info:"
    assert "[7] Subject A" in r.replies
    assert "[9] Subject B" in r.replies
    assert r.next_state["command"] == "BULLETIN_READ"


def test_read_bulletin_shows_content():
    store = FakeStore(content={7: ("AA", "2026-07-01", "Subject A", "Body", "u")})
    r = BulletinFlow().advance("7", st("BULLETIN_READ", board="Info"), deps(store))
    assert "From: AA" in r.replies[0]
    assert "Subject: Subject A" in r.replies[0]
    assert "Body" in r.replies[0]
    assert r.goto == "bbs"


# --- post + urgent permission ---------------------------------------------

def test_post_to_general_prompts_for_subject():
    r = BulletinFlow().advance("p", st("BULLETIN_ACTION", board="General"), deps())
    assert "subject" in r.replies[0].lower()
    assert r.next_state["command"] == "BULLETIN_POST"


def test_urgent_post_denied_when_not_allowed():
    d = deps(node_id="!me", allowed=["!someone_else"])
    r = BulletinFlow().advance("p", st("BULLETIN_ACTION", board="Urgent"), d)
    assert "don't have permission" in r.replies[0]
    assert r.goto == "bbs"


def test_urgent_post_allowed_when_listed():
    d = deps(node_id="!me", allowed=["!me"])
    r = BulletinFlow().advance("p", st("BULLETIN_ACTION", board="Urgent"), d)
    assert "subject" in r.replies[0].lower()
    assert r.next_state["command"] == "BULLETIN_POST"


def test_empty_allow_list_permits_urgent_post():
    # Matches legacy: no allow-list configured => anyone may post.
    d = deps(node_id="!me", allowed=[])
    r = BulletinFlow().advance("p", st("BULLETIN_ACTION", board="Urgent"), d)
    assert r.next_state["command"] == "BULLETIN_POST"


# --- content accumulation + commit ----------------------------------------

def test_content_accumulates_until_end():
    state = st("BULLETIN_POST_CONTENT", board="General", subject="Hi", content="")
    r = BulletinFlow().advance("line one", state, deps())
    assert r.replies == []
    assert r.next_state["content"] == "line one\n"


def test_end_persists_and_returns_to_bbs():
    store = FakeStore()
    state = st("BULLETIN_POST_CONTENT", board="General", subject="Hi", content="body\n")
    r = BulletinFlow().advance("END", state, deps(store))
    assert store.added == [("General", "ME", "Hi", "body\n")]
    assert "posted to General" in r.replies[0]
    assert r.goto == "bbs"


def test_end_without_node_info_errors():
    store = FakeStore()
    state = st("BULLETIN_POST_CONTENT", board="General", subject="Hi", content="x")
    d = deps(store, node_id="!gone", roster={})   # acting node not in roster
    r = BulletinFlow().advance("END", state, d)
    assert "Unable to retrieve your node information" in r.replies[0]
    assert r.next_state is None
    assert store.added == []


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
