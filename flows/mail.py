"""Mail conversation: read, send, reply, delete.

Collapses the MAIL step machine (steps 1-8) and the CHECK_MAIL read/confirm
steps into one flow. Pure: mailbox reads and writes go through the injected
store, node resolution through the injected lookup, and the "you have new
mail" nudge to the recipient rides back as a notification for the router to
send — the flow never touches the radio.

The quick-command entry points (SM,, and CM) are still seeded by the legacy
handlers; this flow owns every stepped state they lead into.
"""

from flows.base import FlowResult, GOTO_MAIN

MAIL_MENU = ("✉️Mail Menu✉️\nWhat would you like to do with mail?\n"
             "[R]ead  [S]end E[X]IT")


def _collapse(message):
    message = message.strip()
    if len(message) == 2 and message[1].lower() == "x":
        message = message[0]
    return message


SEND_USAGE = "Send Mail Quick Command format:\nSM,,{short_name},,{subject},,{message}"


class MailFlow:
    TOPICS = ["MAIL", "CHECK_MAIL"]
    QUICK_COMMANDS = {"sm,,": "quick_send", "cm": "quick_check"}

    def entry(self, deps):
        return FlowResult(replies=[MAIL_MENU], next_state={"command": "MAIL", "step": 1})

    # --- quick commands ---------------------------------------------------

    def quick_send(self, message, deps):
        """SM,,{short_name},,{subject},,{message} — send without stepping."""
        parts = message.split(",,", 3)
        if len(parts) != 4:
            return FlowResult(replies=[SEND_USAGE], keep_state=True)

        _, short_name, subject, content = parts
        nodes = deps.lookup.node_info(short_name.lower())
        if not nodes:
            return FlowResult(replies=[f"Node with short name '{short_name}' not found."],
                              keep_state=True)
        if len(nodes) > 1:
            return FlowResult(
                replies=[f"Multiple nodes with short name '{short_name}' found. "
                         f"Please be more specific."],
                keep_state=True)

        recipient_id = nodes[0].id
        recipient_name = deps.lookup.node_name(recipient_id)
        sender_short_name = deps.lookup.short_name(deps.node_id)
        deps.store.add_mail(deps.node_id, sender_short_name, recipient_id, subject, content)

        notification = (f"You have a new mail message from {sender_short_name}. "
                        f"Check your mailbox by responding to this message with CM.")
        return FlowResult(replies=[f"Mail has been sent to {recipient_name}."],
                          notifications=[(recipient_id, notification)],
                          keep_state=True)

    def quick_check(self, message, deps):
        """CM — list the mailbox and wait for a number."""
        mail = deps.store.get_mail(deps.node_id)
        if not mail:
            return FlowResult(replies=["You have no new messages."], keep_state=True)

        listing = "📬 You have the following messages:\n"
        for i, msg in enumerate(mail):
            listing += f"{i + 1:02d}. From: {msg[1]}, Subject: {msg[2]}\n"
        listing += "\nPlease reply with the number of the message you want to read."
        return FlowResult(replies=[listing],
                          next_state={"command": "CHECK_MAIL", "step": 1, "mail": mail})

    def advance(self, message, state, deps):
        command = state.get("command")
        step = state.get("step")
        if command == "CHECK_MAIL":
            if step == 1:
                return self._check_read(message, state, deps)
            if step == 2:
                return self._confirm(message, state, deps)
            return FlowResult(next_state=state)

        # command == "MAIL"
        handler = {
            1: self._menu, 2: self._open, 3: self._recipient,
            4: self._disposition, 5: self._subject, 6: self._pick_node,
            7: self._compose, 8: self._again,
        }.get(step)
        if handler is None:
            return FlowResult(next_state=state)
        return handler(message, state, deps)

    # --- MAIL -------------------------------------------------------------

    def _menu(self, message, state, deps):
        choice = _collapse(message).lower()
        if choice == "r":
            mail = deps.store.get_mail(deps.node_id)
            if not mail:
                return FlowResult(replies=["There are no messages in your mailbox.📭"],
                                  next_state=None)
            replies = [f"You have {len(mail)} mail messages. "
                       f"Select a message number to read:"]
            replies += [f"-{m[0]}-\nDate: {m[3]}\nFrom: {m[1]}\nSubject: {m[2]}"
                        for m in mail]
            return FlowResult(replies=replies,
                              next_state={"command": "MAIL", "step": 2})
        if choice == "s":
            return FlowResult(
                replies=["What is the Short Name of the node you want to leave a message for?"],
                next_state={"command": "MAIL", "step": 3})
        # 'x' never reaches here (intercepted upstream); mirror the no-op.
        return FlowResult(next_state=state)

    def _open(self, message, state, deps):
        mail_id = int(message)
        content = deps.store.get_mail_content(mail_id, deps.node_id)
        if content is None:
            return FlowResult(replies=["Mail not found"], next_state=None)
        sender, date, subject, body, unique_id = content
        return FlowResult(
            replies=[f"Date: {date}\nFrom: {sender}\nSubject: {subject}\n{body}",
                     "What would you like to do with this message?\n[K]eep  [D]elete  [R]eply"],
            next_state={"command": "MAIL", "step": 4, "mail_id": mail_id,
                        "unique_id": unique_id, "sender": sender,
                        "subject": subject, "content": body})

    def _recipient(self, message, state, deps):
        short_name = message.lower()
        nodes = deps.lookup.node_info(short_name)
        if not nodes:
            return FlowResult(replies=["I'm unable to find that node in my database.", MAIL_MENU],
                              next_state={"command": "MAIL", "step": 1})
        if len(nodes) == 1:
            recipient_id = nodes[0].id
            recipient_name = deps.lookup.node_name(recipient_id)
            return FlowResult(
                replies=[f"What is the subject of your message to {recipient_name}?\nKeep it short."],
                next_state={"command": "MAIL", "step": 5, "recipient_id": recipient_id})
        replies = ["There are multiple nodes with that short name. "
                   "Which one would you like to leave a message for?"]
        replies += [f"[{i}] {n.long_name}" for i, n in enumerate(nodes)]
        return FlowResult(replies=replies,
                          next_state={"command": "MAIL", "step": 6, "nodes": nodes})

    def _disposition(self, message, state, deps):
        choice = message.lower()
        if choice == "d":
            deps.store.delete_mail(state["unique_id"], deps.node_id)
            return FlowResult(replies=["The message has been deleted 🗑️"], next_state=None)
        if choice == "r":
            return FlowResult(
                replies=[f"Send your reply to {state['sender']} now, followed by a message with END"],
                next_state={"command": "MAIL", "step": 7,
                            "reply_to_mail_id": state["mail_id"],
                            "subject": f"Re: {state['subject']}", "content": ""})
        return FlowResult(replies=["The message has been kept in your inbox.✉️"], next_state=None)

    def _subject(self, message, state, deps):
        return FlowResult(
            replies=["Send your message. You can send it in multiple messages if it's too long "
                     "for one.\nSend a single message with END when you're done"],
            next_state={"command": "MAIL", "step": 7,
                        "recipient_id": state["recipient_id"], "subject": message, "content": ""})

    def _pick_node(self, message, state, deps):
        selected = state["nodes"][int(message)]
        recipient_id = selected.id
        recipient_name = deps.lookup.node_name(recipient_id)
        return FlowResult(
            replies=[f"What is the subject of your message to {recipient_name}?\nKeep it short."],
            next_state={"command": "MAIL", "step": 5, "recipient_id": recipient_id})

    def _compose(self, message, state, deps):
        if message.lower() != "end":
            return FlowResult(next_state={**state, "content": state["content"] + message + "\n"})

        if "reply_to_mail_id" in state:
            recipient_id = deps.store.sender_id_by_mail_id(state["reply_to_mail_id"])
        else:
            recipient_id = state.get("recipient_id")
        subject = state["subject"]
        content = state["content"]
        recipient_name = deps.lookup.node_name(recipient_id)
        sender_short_name = deps.lookup.short_name(deps.node_id)

        deps.store.add_mail(deps.node_id, sender_short_name, recipient_id, subject, content)
        notification = (f"You have a new mail message from {sender_short_name}. "
                        f"Check your mailbox by responding to this message with CM.")
        return FlowResult(
            replies=[f"Mail has been posted to the mailbox of {recipient_name}.\n(╯°□°)╯📨📬"],
            notifications=[(recipient_id, notification)],
            next_state={"command": "MAIL", "step": 8})

    def _again(self, message, state, deps):
        if message.lower() == "y":
            return FlowResult(replies=[MAIL_MENU], next_state={"command": "MAIL", "step": 1})
        return FlowResult(replies=["Okay, feel free to send another command."], next_state=None)

    # --- CHECK_MAIL (entered from the CM quick command) -------------------

    def _check_read(self, message, state, deps):
        mail = state.get("mail", [])
        try:
            number = int(message) - 1
        except ValueError:
            return FlowResult(replies=["Invalid input. Please enter a valid message number."],
                              next_state=state)
        if number < 0 or number >= len(mail):
            return FlowResult(replies=["Invalid message number. Please try again."],
                              next_state=state)
        mail_id = mail[number][0]
        sender, date, subject, body, unique_id = deps.store.get_mail_content(mail_id, deps.node_id)
        return FlowResult(
            replies=[f"Date: {date}\nFrom: {sender}\nSubject: {subject}\n\n{body}",
                     "What would you like to do with this message?\n[K]eep  [D]elete  [R]eply"],
            next_state={"command": "CHECK_MAIL", "step": 2, "mail_id": mail_id,
                        "unique_id": unique_id, "sender": sender,
                        "subject": subject, "content": body})

    def _confirm(self, message, state, deps):
        choice = _collapse(message).lower()
        if choice == "d":
            deps.store.delete_mail(state["unique_id"], deps.node_id)
            return FlowResult(replies=["The message has been deleted 🗑️"], next_state=None)
        if choice == "r":
            return FlowResult(
                replies=[f"Send your reply to {state['sender']} now, followed by a message with END"],
                next_state={"command": "MAIL", "step": 7,
                            "reply_to_mail_id": state["mail_id"],
                            "subject": f"Re: {state['subject']}", "content": ""})
        return FlowResult(replies=["The message has been kept in your inbox.✉️"], next_state=None)
