"""v1.1 alignment: hashed fingerprints, STATUS heartbeat, manifest, URGENT lane."""
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import timedelta

from postbox import core, watch
from postbox.transport import LocalTransport

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WHEN = core.now(8)


def run(root, *args, expect=None):
    env = os.environ.copy()
    env["PYTHONPATH"] = REPO + os.pathsep + env.get("PYTHONPATH", "")
    env["POSTBOX_STATE"] = os.path.join(root, ".state")
    proc = subprocess.run([sys.executable, "-m", "postbox", "--root", root] + list(args),
                          capture_output=True, text=True, encoding="utf-8", env=env, cwd=root)
    if expect is not None:
        assert proc.returncode == expect, (proc.returncode, proc.stdout, proc.stderr)
    return proc


def one_agent(tmp_path):
    root = str(tmp_path / "alice")
    shared = tmp_path / "mailbox"
    os.makedirs(root)
    run(root, "init", "--path", str(shared), "--agent", "alice", expect=0)
    return root, str(shared)


def test_md5_catches_same_size_same_mtime_change(tmp_path):
    box = tmp_path / "box"
    box.mkdir()
    target = box / "a.md"
    target.write_text("AAAA", encoding="utf-8")
    os.utime(target, (1_700_000_000, 1_700_000_000))
    state = str(tmp_path / "state")
    transport = LocalTransport(str(box))

    assert watch.run(transport, ["."], state)[0] == 10
    assert watch.run(transport, ["."], state)[0] == 0

    target.write_text("BBBB", encoding="utf-8")          # same size, different bytes
    os.utime(target, (1_700_000_000, 1_700_000_000))     # same mtime too
    code, out = watch.run(transport, ["."], state)
    assert code == 10
    assert "CHANGED|+1|-1" in out
    assert hashlib.md5(b"BBBB").hexdigest() in out


def test_own_status_heartbeat_does_not_wake_me(tmp_path):
    box = tmp_path / "box"
    box.mkdir()
    (box / "STATUS_alice.md").write_text(
        core.render_status("alice", "laptop", "idle", "none", "none", "-", core.fmt_ts(WHEN)),
        encoding="utf-8")
    state = str(tmp_path / "state")
    transport = LocalTransport(str(box))
    watch.run(transport, ["."], state, self_agent="alice")
    assert watch.run(transport, ["."], state, self_agent="alice")[0] == 0

    (box / "STATUS_alice.md").write_text(
        core.render_status("alice", "laptop", "working", "t-1", "none", "-", core.fmt_ts(WHEN)),
        encoding="utf-8")
    assert watch.run(transport, ["."], state, self_agent="alice")[0] == 0


def test_urgent_lane_only_looks_at_the_prefix(tmp_path):
    box = tmp_path / "box"
    box.mkdir()
    (box / "2026-11-02_TASK-x_alice-to-bob_normal.md").write_text("x", encoding="utf-8")
    state = str(tmp_path / "state")
    transport = LocalTransport(str(box))
    assert watch.run(transport, ["."], state, prefix="URGENT_")[0] == 0

    name = core.task_filename("x", "alice", "bob", "fire", WHEN, urgent=True)
    assert name.startswith("URGENT_")
    (box / name).write_text("fire", encoding="utf-8")
    code, out = watch.run(transport, ["."], state, prefix="URGENT_")
    assert code == 10 and "URGENT_" in out
    assert "normal.md" not in out


def test_urgent_task_parses_back(tmp_path):
    task_id = core.make_task_id("alice", "bob", WHEN, 1)
    name = core.task_filename(task_id, "alice", "bob", "fire", WHEN, urgent=True)
    task = core.Task.parse(name, core.render_task(task_id, "alice", "bob", "fire", "go",
                                                  created_at=core.fmt_ts(WHEN)))
    assert task.urgent is True
    plain = core.task_filename(task_id, "alice", "bob", "fire", WHEN)
    assert core.Task.parse(plain, "x").urgent is False


def test_status_v11_fields_and_heartbeat_only(tmp_path):
    root, shared = one_agent(tmp_path)
    run(root, "status", "idle", "--note", "waiting for review", expect=0)
    path = os.path.join(shared, "STATUS_alice.md")
    with open(path, encoding="utf-8") as fh:
        first = fh.read()
    assert "protocol: 1.1" in first
    assert "heartbeat_at:" in first
    updated = core.parse_status(first)["updated_at"]

    time.sleep(1.1)
    run(root, "status", "--heartbeat", expect=0)
    with open(path, encoding="utf-8") as fh:
        second = fh.read()
    fields = core.parse_status(second)
    assert fields["updated_at"] == updated          # heartbeat is its own clock
    assert fields["heartbeat_at"] != fields["updated_at"]
    assert fields["state"] == "idle" and fields["note"] == "waiting for review"


def test_result_must_list_what_it_delivered(tmp_path):
    root, shared = one_agent(tmp_path)
    task = run(root, "new", "--to", "bob", "--title", "t", "--ask", "go", expect=0)
    task_id = task.stdout.split("\t")[0]
    run(root, "--agent", "bob", "ack", task_id, expect=0)

    missing = run(root, "--agent", "bob", "result", task_id, "--text",
                  "delivered everything you asked for here", "--artifact", "nope.md", expect=2)
    assert "artifact not found" in missing.stderr

    bare = run(root, "--agent", "bob", "result", task_id, "--text",
               "delivered everything you asked for here", expect=2)
    assert "--artifact" in bare.stderr

    out = tmp_path / "out.md"
    out.write_text("done\n", encoding="utf-8")
    made = run(root, "--agent", "bob", "result", task_id, "--text",
               "delivered everything you asked for here", "--artifact", str(out), expect=0)
    body = open(os.path.join(shared, made.stdout.strip()), encoding="utf-8").read()
    assert "| out.md |" in body
    assert core.sha256_bytes(out.read_bytes()) in body


def test_lint_flags_urgent_without_prefix(tmp_path):
    root, shared = one_agent(tmp_path)
    run(root, "new", "--to", "bob", "--title", "quiet", "--ask", "go",
        "--priority", "urgent", expect=0)
    proc = run(root, "lint", expect=0)
    assert "urgent_without_prefix" in proc.stdout


def test_lint_flags_a_stale_heartbeat(tmp_path):
    root, shared = one_agent(tmp_path)
    old = core.fmt_ts(core.now(8) - timedelta(minutes=200))
    with open(os.path.join(shared, "STATUS_alice.md"), "w", encoding="utf-8") as fh:
        fh.write(core.render_status("alice", "laptop", "online", "none", "none", "-",
                                    old, heartbeat_at=old))
    proc = run(root, "lint", expect=0)
    assert "lost_contact" in proc.stdout
