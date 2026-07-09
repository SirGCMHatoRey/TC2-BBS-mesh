"""Bulletin conversation: browse boards, read, post.

Collapses six legacy state strings (BULLETIN_MENU / BULLETIN_ACTION /
BULLETIN_READ / BULLETIN_POST / BULLETIN_POST_CONTENT) and the urgent
permission + broadcast branches into one flow. The set of boards and the
urgent policy come from the Board value type; enforcement of the allow-list
stays here, where the acting node is known.

Pure: reads and writes go through the injected store; the confirmation text
is returned, and the post's side effects (peer sync, urgent broadcast) live
inside the store for now (candidate 02 will lift them out).
"""

import board as boards
from flows.base import FlowResult, GOTO_MAIN, GOTO_BBS

BULLETIN_MENU = ("📰Bulletin Menu📰\nWhich board would you like to enter?\n"
                 "[G]eneral  [I]nfo  [N]ews  [U]rgent")

_LETTER_TO_BOARD = {
    "g": boards.GENERAL,
    "i": boards.INFO,
    "n": boards.NEWS,
    "u": boards.URGENT,
}


class BulletinFlow:
    TOPICS = [
        "BULLETIN_MENU",
        "BULLETIN_ACTION",
        "BULLETIN_READ",
        "BULLETIN_POST",
        "BULLETIN_POST_CONTENT",
    ]

    def entry(self, deps):
        return FlowResult(replies=[BULLETIN_MENU],
                          next_state={"command": "BULLETIN_MENU", "step": 1})

    def advance(self, message, state, deps):
        command = state.get("command")
        if command == "BULLETIN_MENU":
            return self._select_board(message, deps)
        if command == "BULLETIN_ACTION":
            return self._read_or_post(message, state, deps)
        if command == "BULLETIN_READ":
            return self._read_bulletin(message, state, deps)
        if command == "BULLETIN_POST":
            return self._take_subject(message, state)
        if command == "BULLETIN_POST_CONTENT":
            return self._take_content(message, state, deps)
        return FlowResult(next_state=state)

    def _select_board(self, message, deps):
        board = _LETTER_TO_BOARD.get(message.lower().strip())
        if board is None:
            # Legacy dropped unrecognized menu input back to the main menu.
            return FlowResult(goto=GOTO_MAIN)
        bulletins = deps.store.get_bulletins(board.name)
        reply = f"{board.name} has {len(bulletins)} messages.\n[R]ead  [P]ost"
        return FlowResult(
            replies=[reply],
            next_state={"command": "BULLETIN_ACTION", "step": 2, "board": board.name})

    def _read_or_post(self, message, state, deps):
        board_name = state["board"]
        choice = message.lower().strip()

        if choice == "r":
            bulletins = deps.store.get_bulletins(board_name)
            if not bulletins:
                return FlowResult(replies=[f"No bulletins in {board_name}."],
                                  goto=GOTO_BBS)
            replies = [f"Select a bulletin number to view from {board_name}:"]
            replies += [f"[{b[0]}] {b[1]}" for b in bulletins]
            return FlowResult(
                replies=replies,
                next_state={"command": "BULLETIN_READ", "step": 3, "board": board_name})

        if choice == "p":
            board = boards.Board.from_name(board_name)
            if board is not None and board.requires_post_permission:
                if deps.allowed_nodes and deps.node_id not in deps.allowed_nodes:
                    return FlowResult(
                        replies=["You don't have permission to post to this board."],
                        goto=GOTO_BBS)
            return FlowResult(
                replies=["What is the subject of your bulletin? Keep it short."],
                next_state={"command": "BULLETIN_POST", "step": 4, "board": board_name})

        # Anything else fell through to the main menu in the legacy path.
        return FlowResult(goto=GOTO_MAIN)

    def _read_bulletin(self, message, state, deps):
        bulletin_id = int(message)
        sender_short_name, date, subject, content, _ = \
            deps.store.get_bulletin_content(bulletin_id)
        reply = (f"From: {sender_short_name}\nDate: {date}\nSubject: {subject}\n"
                 f"- - - - - - -\n{content}")
        return FlowResult(replies=[reply], goto=GOTO_BBS)

    def _take_subject(self, message, state):
        return FlowResult(
            replies=["Send the contents of your bulletin. Send a message with END when finished."],
            next_state={"command": "BULLETIN_POST_CONTENT", "step": 5,
                        "board": state["board"], "subject": message, "content": ""})

    def _take_content(self, message, state, deps):
        if message.lower() != "end":
            return FlowResult(next_state={**state,
                                          "content": state["content"] + message + "\n"})

        board = state["board"]
        subject = state["subject"]
        content = state["content"]
        node = deps.roster.get(deps.node_id)
        if node is None:
            return FlowResult(replies=["Error: Unable to retrieve your node information."],
                              next_state=None)
        sender_short_name = node["user"].get("shortName", f"Node {deps.node_num}")
        deps.store.add_bulletin(board, sender_short_name, subject, content)
        reply = (f"Your bulletin '{subject}' has been posted to {board}.\n"
                 f"(╯°□°)╯📄📌[{board}]")
        return FlowResult(replies=[reply], goto=GOTO_BBS)
