"""Six ways the real world breaks a folder queue.

None of these are hypothetical: clock skew, double dispatch, a file cut in half by
a crash, an event whose task never arrived, a replayed history, and a reader that
is a few seconds behind. The tool is allowed to be honest about all six; it is not
allowed to lose work or invent an owner.
"""
import json
import os
import random

from postbox import core
from postbox.config import Config
from postbox.state import derive_state
from test_cli import init_agents, run


def _set_cfg(root, **values):
    path = os.path.join(root, ".postbox", "config.json")
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    data.update(values)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False)


def test_two_machines_eight_hours_apart_never_share_an_id(tmp_path):
    roots, _shared = init_agents(tmp_path)
    _set_cfg(roots["alice"], utc_offset_hours=8)
    _set_cfg(roots["bob"], utc_offset_hours=-5)

    first = run(roots["alice"], "new", "--to", "bob", "--title", "北京发出", "--ask", "x", expect=0)
    second = run(roots["bob"], "new", "--to", "alice", "--title", "纽约发出", "--ask", "y", expect=0)
    id_a, id_b = first.stdout.split("\t")[0], second.stdout.split("\t")[0]

    assert id_a != id_b
    listing = run(roots["alice"], "ls", "--all").stdout
    assert id_a in listing and id_b in listing
    assert "duplicate_id" not in run(roots["alice"], "lint").stdout


def test_dispatching_the_same_job_twice_is_two_tasks_and_nothing_is_lost(tmp_path):
    roots, _shared = init_agents(tmp_path)
    first = run(roots["alice"], "new", "--to", "bob", "--title", "同一句话", "--ask", "做", expect=0)
    second = run(roots["alice"], "new", "--to", "bob", "--title", "同一句话", "--ask", "做", expect=0)
    id_a, id_b = first.stdout.split("\t")[0], second.stdout.split("\t")[0]

    assert id_a != id_b, "identical dispatch must still get its own id"
    listing = run(roots["alice"], "ls", "--all").stdout
    assert id_a in listing and id_b in listing
    assert "duplicate_id" not in run(roots["alice"], "lint").stdout


def test_a_file_cut_in_half_by_a_crash_does_not_stop_the_queue(tmp_path):
    roots, shared = init_agents(tmp_path)
    half = os.path.join(shared, "20260101-0000-alice-to-bob-77.md")
    with open(half, "w", encoding="utf-8") as fh:      # no closing fence, no body
        fh.write("---\ntask: 20260101-0000-alice-to-bob-77\ntitle: cut off")

    assert run(roots["alice"], "ls", "--all").returncode == 0
    assert run(roots["alice"], "inbox").returncode == 0
    assert run(roots["bob"], "watch").returncode in (0, 10)


def test_an_event_whose_task_never_arrived_is_reported(tmp_path):
    roots, shared = init_agents(tmp_path)
    ghost = os.path.join(shared, "20260101-0000-ghost-to-bob-01_ACK_bob.md")
    with open(ghost, "w", encoding="utf-8") as fh:
        fh.write("---\ntask: 20260101-0000-ghost-to-bob-01\nkind: ACK\n---\nok\n")

    out = run(roots["alice"], "lint")
    assert "orphan_event" in (out.stdout + out.stderr)


def test_replaying_the_history_always_gives_the_same_state(tmp_path):
    roots, _shared = init_agents(tmp_path)
    created = run(roots["alice"], "new", "--to", "bob", "--title", "重放", "--ask", "做", expect=0)
    task_id = created.stdout.split("\t")[0]
    run(roots["bob"], "ack", task_id, expect=0)
    run(roots["bob"], "note", task_id, "--text", "开始动手了", expect=0)

    cfg = Config.load(roots["alice"])
    cfg.agent = "alice"
    from postbox.cli import mailbox
    box = mailbox(cfg).sync()
    entry = box.get(task_id)

    assert entry.state == "working"
    events = list(entry.events)
    for _ in range(5):
        random.shuffle(events)
        assert derive_state(entry.task, events) == "working"


def test_a_reader_that_is_behind_catches_up_on_the_next_sync(tmp_path):
    roots, _shared = init_agents(tmp_path)
    cfg = Config.load(roots["alice"])
    cfg.agent = "alice"
    from postbox.cli import mailbox

    box = mailbox(cfg).sync()
    seen = {e.task.task_id for e in box.entries}

    created = run(roots["alice"], "new", "--to", "bob", "--title", "后来才同步到", "--ask", "x", expect=0)
    task_id = created.stdout.split("\t")[0]

    assert task_id not in seen, "the first read happened before the task existed"
    box.sync()
    assert task_id in {e.task.task_id for e in box.entries}
    assert box.get(task_id).state == "new"
    assert core.MD in created.stdout or task_id in created.stdout
