import os
import time

import pytest

from postbox import core
from postbox.state import Mailbox, Ledger, derive_state
from postbox.transport import LocalTransport


def write(dir_path, name, text, mtime=None):
    path = os.path.join(dir_path, name)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    if mtime:
        os.utime(path, (mtime, mtime))
    return path


def event(kind, agent, mtime, path=None):
    return core.Event(path=path or "%s_%s" % (kind, agent), task_path="t.md",
                      kind=kind, agent=agent, seq=1, mtime="2026-11-02T00:00:%02d" % mtime)


def make_task(needs_owner=False):
    return core.Task(path="2026-11-02_TASK-x_alice-to-bob_t.md", task_id="x", date="2026-11-02",
                     route="alice-to-bob", sender="alice", recipient="bob", title="t",
                     meta={"needs_owner_confirm": "yes" if needs_owner else "no"})


def test_state_machine_transitions():
    task = make_task()
    assert derive_state(task, []) == "new"
    assert derive_state(task, [event("ACK", "bob", 1)]) == "ack"
    assert derive_state(task, [event("ACK", "bob", 1), event("NOTE", "bob", 2)]) == "working"
    assert derive_state(task, [event("ACK", "bob", 1), event("BLOCKED", "bob", 2)]) == "blocked"
    assert derive_state(task, [event("QUESTION", "bob", 1)]) == "question"
    assert derive_state(task, [event("ACK", "bob", 1), event("RESULT", "bob", 2)]) == "done"
    # a later NOTE cannot resurrect a finished task
    assert derive_state(task, [event("RESULT", "bob", 1), event("NOTE", "bob", 2)]) == "done"


def test_owner_gate_blocks_progress_even_if_acked():
    task = make_task(needs_owner=True)
    assert derive_state(task, [event("ACK", "bob", 1)]) == "waiting_owner"
    assert derive_state(task, [event("ACK", "bob", 1), event("OWNER_OK", "owner", 2)]) == "ack"
    assert derive_state(task, [event("OWNER_NO", "owner", 2)]) == "rejected"


def test_mailbox_reads_a_real_folder(mailbox):
    when = core.now(8)
    task_id = core.make_task_id("alice", "bob", when, 1)
    task_name = core.task_filename(task_id, "alice", "bob", "weekly", when)
    write(mailbox, task_name, core.render_task(task_id, "alice", "bob", "weekly", "do it",
                                               created_at=core.fmt_ts(when)), time.time() - 300)
    ack = core.event_filename(task_name, "ACK", "bob")
    write(mailbox, ack, core.render_event("ACK", "bob", core.fmt_ts(when), "on it"),
          time.time() - 200)
    write(mailbox, "STATUS_bob.md", core.render_status("bob", "box", "working", task_id,
                                                       "none", "-", core.fmt_ts(when)))
    write(mailbox, "任务模板.md", "# unrelated file\n")

    box = Mailbox(LocalTransport(str(mailbox))).sync()
    assert len(box.entries) == 1
    entry = box.get(task_id)
    assert entry.state == "ack"
    assert [e.kind for e in entry.events] == ["ACK"]
    assert box.statuses()["bob"]["state"] == "working"
    assert [e.task.task_id for e in box.pending_for("bob")] == [task_id]
    assert [e.task.task_id for e in box.replies_for("alice")] == [task_id]
    assert box.pending_for("alice") == []


def test_mailbox_ignores_event_without_task(mailbox):
    write(mailbox, "2026-11-02_TASK-ghost_alice-to-bob_x_ACK_bob.md",
          core.render_event("ACK", "bob", "2026-11-02 09:00:00 +0800", "hi"))
    box = Mailbox(LocalTransport(str(mailbox))).sync()
    assert box.entries == []


def test_ledger_roundtrip(tmp_path):
    led = Ledger(str(tmp_path / "inbox.json"))
    assert not led.is_seen("x", "1")
    led.seen("x", "1")
    led.save()
    assert Ledger(str(tmp_path / "inbox.json")).is_seen("x", "1")


def test_get_by_fragment_is_unique_only(mailbox):
    when = core.now(8)
    for seq in (1, 2):
        task_id = core.make_task_id("alice", "bob", when, seq)
        name = core.task_filename(task_id, "alice", "bob", "same", when)
        write(mailbox, name, core.render_task(task_id, "alice", "bob", "same", "x",
                                              created_at=core.fmt_ts(when)))
    box = Mailbox(LocalTransport(str(mailbox))).sync()
    with pytest.raises(KeyError):
        box.get("-0")                      # matches both: refuse to guess
    assert box.get("-01").task.task_id.endswith("-01")
