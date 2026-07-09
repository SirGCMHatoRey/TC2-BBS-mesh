"""Where each Node stands in its conversation.

Sending moved to Transport; node lookups moved to roster. What is left is the
per-node conversation state the Session reads and writes.
"""

user_states = {}


def update_user_state(user_id, state):
    user_states[user_id] = state


def get_user_state(user_id):
    return user_states.get(user_id, None)
