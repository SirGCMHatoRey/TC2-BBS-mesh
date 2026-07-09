# Bugs found and fixed during the Session/Flow refactor

None of these were hunted. Each surfaced while rewriting the code that
contained it — which is the argument for the refactor, not a bonus from it.

Every entry was reproduced before being fixed, and each has a regression test.
Behaviour changes are called out explicitly: the refactor was otherwise
behaviour-preserving, guarded by the characterization suite in
`test_characterization.py`.

---

## 1. Any node could post to the Urgent board and broadcast to the whole mesh

**Severity:** access control bypass.

`[allow_list] allowed_nodes` in `config.ini` restricts who may post to the
Urgent board — a post there broadcasts a notice to every node on the mesh.
The menu path (`[B]ulletins → [U]rgent → [P]ost`) checked the allow-list.
The `PB,,` quick command never did.

```
PB,,Urgent,,Fake alert,,ignore me
```

from a node absent from `allowed_nodes` posted the bulletin and triggered the
mesh-wide broadcast.

**Cause:** the check lived inline in the menu handler, so the second caller
never inherited it.

**Fix:** both paths now go through one `_may_post()` in `flows/bulletin.py`.

Commit `6257db4`. Tests: `test_bulletin_flow.py::test_quick_post_to_urgent_respects_the_allow_list`,
`test_characterization.py::test_quick_post_bulletin_to_urgent_respects_allow_list`.

---

## 2. A synced Urgent bulletin broadcast to the mesh twice

Receiving an Urgent bulletin from a peer BBS node sent two identical
`💥NEW URGENT BULLETIN💥` notices to the whole mesh.

**Cause:** the broadcast decision existed in two places — inside
`db_operations.add_bulletin` (outside the `if bbs_nodes` guard) and again in
the sync-receive branch of `message_processing`.

**Fix:** persistence no longer transmits. `Replication.publish(event, origin)`
is the single place that decides both sync and broadcast, driven by the
Board's `broadcasts_on_post` policy rather than a `board.lower() == "urgent"`
string test.

**Behaviour change:** one broadcast instead of two.

Commit `4fb33ef`. Test: `test_characterization.py::test_synced_urgent_bulletin_broadcasts_once`.

---

## 3. Replicated bulletin deletions silently did nothing

`delete_bulletin` deleted by the local autoincrement `id`:

```sql
DELETE FROM bulletins WHERE id = ?
```

while its only caller — the `DELETE_BULLETIN|` sync branch — passed a
`unique_id`. The statement matched no rows, every time. Nobody noticed because
nothing in the codebase ever *originates* a bulletin deletion (`db_admin.py`
deletes directly, without syncing), so the broken path was only ever reached
from a peer.

**Fix:** `delete_bulletin(unique_id)` matches on `unique_id`, the identity
peers actually share, and returns `None` when the bulletin is absent.

**Behaviour change:** a replicated deletion now deletes.

Commit `4fb33ef`. Test: `test_characterization.py::test_synced_bulletin_deletion_removes_it`.

---

## 4. The `CHP,,` quick command could never succeed

```python
parts = message.split("|", 3)          # splits on "|"
if len(parts) != 3:
    send_message("Post Channel Quick Command format:\nCHP,,{channel_name},,{channel_url}")
```

The parser split on `|` while its own usage text promised `,,`. Any well-formed
`CHP,,Name,,url` produced a single part, failed the length check, and printed
the usage. Adding a channel by quick command had never worked.

**Fix:** `split(",,", 2)`, matching the documented format.

**Behaviour change:** the command works.

Commit `6257db4`. Tests: `test_channel_flow.py::test_quick_post_adds_channel`,
`test_characterization.py::test_quick_post_channel_actually_works`.

---

## 5 & 6. Every JS8Call message crashed the JS8Call thread

Two independent faults on the same code path:

```python
def insert_message(self, table, sender, recipient, message):
    ...
    self.db_conn.execute(..., (sender, receiver_or_group, message))   # 5: undefined name
```

`receiver_or_group` does not exist; the parameter is `recipient`. The
surrounding `except sqlite3.Error` does not catch `NameError`, so it escaped.

```python
self.insert_urgent('urgent', sender, receiver, msg)                   # 6: no such method
```

`insert_urgent` was never defined — `AttributeError`.

Between them, every `RX.DIRECTED` message the bridge received raised: urgent
messages hit the missing method, group and station messages hit the undefined
name. The exception escaped `process()`, escaped `connect()` (which catches
only `ConnectionRefusedError`), and killed the client. The JS8Call bridge
stored nothing, ever. It went unnoticed because `example_config.ini` ships with
the `[js8call]` section commented out.

**Fix:** writes go through `js8_db.Js8Database.insert(table, sender, counterparty, message)`,
which takes the column from a table allow-list. Both call sites use it.

**Behaviour change:** the bridge stores messages.

Commit `f8b0352`. Tests: `test_js8_db.py` (all), verified end-to-end against
`JS8CallClient.process`.

---

## 7. The JS8Call reader and writer used different databases

`JS8CallClient` wrote to the configured `[js8call] db_file`. The three read
handlers each hardcoded `sqlite3.connect('js8call.db')`. Any custom `db_file`
meant the BBS browsed an empty database while the bridge filled another.

**Fix:** one `settings.js8_database()` shared by both.

Commit `f8b0352`.

---

## 8. Browsing JS8Call before it was configured raised at the user

The read handlers ran `SELECT` against tables that only `JS8CallClient` creates.
With the bridge unconfigured, `sqlite3.connect('js8call.db')` created an empty
file and the `SELECT` raised `sqlite3.OperationalError`, uncaught.

**Fix:** `Js8Database` reads return `[]` when the bridge is unconfigured or the
tables do not exist. An unconfigured bridge is an empty inbox, not an error.

**Behaviour change:** "No group messages available." instead of a crash.

Commit `f8b0352`. Test: `test_characterization.py::test_js8call_reads_answer_gracefully_when_unconfigured`.

---

## 9. `handle_help_command` raised `NameError` for unknown menus

```python
if menu_name:
    if menu_name == 'bbs':          response = build_menu(...)
    elif menu_name == 'utilities':  response = build_menu(...)
    # any other name: `response` is never assigned
send_message(response, ...)
```

Unreachable at the time — the function was only ever called with `'bbs'`,
`'utilities'`, or `None` — but a latent trap for the next caller.

**Fix:** `NavigationFlow.show()` falls back to the main menu for any
unrecognized name.

Commit `ff0354a`. Test: `test_navigation_flow.py::test_unknown_menu_name_falls_back_to_main`.

---

## 10. `CB,,` and `PB,,` did not validate the board

`CB,,Sports` raised `StopIteration` out of a generator expression, was swallowed
by a bare `except Exception`, and answered `"Error processing check bulletin
command."` — a message that described the wrong thing.

`PB,,Sports,,subject,,content` did not validate at all, and inserted a bulletin
onto a board no menu can reach and `Replication` will not broadcast.

**Fix:** both resolve the board through `Board.from_name`, which returns `None`
for an unknown name, and answer
`Unknown board 'Sports'. Try General, Info, News, or Urgent.`

**Behaviour change:** honest error messages; no orphan bulletins.

Commit `6257db4`.

---

## Deliberate behaviour changes that were not bugs

- **Adding a Channel now replicates from either entry point.** Previously only
  `CHP,,` synced to peers and the menu did not — an artefact of `add_channel`
  taking the peer list as an optional argument the menu never passed. (Because
  of bug 4, `CHP,,` never ran, so in practice *no* channel ever synced.)
  Commit `14c86fd`.

- **`CHANNEL|` is now recognized as a sync message.** It was already decodable,
  but absent from the prefix list `on_receive` checks, so a peer's channel
  arrived as conversation and was answered with the main menu.
  Commit `14c86fd`.

- **Menu items and fortunes load on first use, not at import.** `command_handlers`
  read `config.ini` at module import, so importing anything required the file to
  exist. The test suite now runs with no `config.ini` present.
  Commit `ff0354a`.

---

## Known, not fixed

- **`JS8CallClient.connect()` blocks forever, and `server.main()` calls it
  inline.** With JS8Call enabled the `while True` loop and its
  `KeyboardInterrupt` shutdown handler are never reached, so the server cannot
  shut down cleanly. Fixing it requires deciding how the bridge is threaded.

- **`db_admin.py` re-declares the entire database schema**, a copy of the one in
  `db_operations.py`. They can drift.
