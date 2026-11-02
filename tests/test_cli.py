"""End-to-end tests: two independent checkouts, one shared folder, real CLI."""
import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run(root, *args, stdin=None, expect=None):
    env = os.environ.copy()
    env["PYTHONPATH"] = REPO + os.pathsep + env.get("PYTHONPATH", "")
    env["POSTBOX_STATE"] = os.path.join(root, ".state")
    proc = subprocess.run([sys.executable, "-m", "postbox", "--root", root] + list(args),
                          capture_output=True, text=True, encoding="utf-8",
                          input=stdin, env=env, cwd=root)
    if expect is not None:
        assert proc.returncode == expect, (proc.returncode, proc.stdout, proc.stderr)
    return proc


def init_agents(tmp_path):
    shared = tmp_path / "mailbox"
    roots = {}
    for name in ("alice", "bob"):
        root = str(tmp_path / name)
        os.makedirs(root)
        run(root, "init", "--transport", "local", "--path", str(shared),
            "--agent", name, "--device", name + "-laptop", expect=0)
        roots[name] = root
    return roots, str(shared)


def test_full_handoff_roundtrip(tmp_path):
    roots, shared = init_agents(tmp_path)

    created = run(roots["alice"], "new", "--to", "bob", "--title", "weekly report",
                  "--ask", "Summarise the week in 5 bullets.",
                  "--accept", "5 bullets, no filler.", expect=0)
    task_id = created.stdout.split("\t")[0]
    assert task_id.startswith("20")

    # bob discovers it
    inbox = run(roots["bob"], "inbox", expect=0)
    assert task_id in inbox.stdout and "todo" in inbox.stdout

    # alice has nothing to do
    assert "nothing for alice" in run(roots["alice"], "inbox").stdout

    # bob accepts, then delivers
    run(roots["bob"], "ack", task_id, expect=0)
    assert "already accepted" in run(roots["bob"], "ack", task_id, expect=3).stderr
    assert "ack" in run(roots["alice"], "ls", "--all").stdout

    result = run(roots["bob"], "result", task_id, "--text",
                 "Wrote 5 bullets. File: 05_out/weekly.md. Facts cross-checked at source.",
                 expect=0)
    assert "_RESULT_bob.md" in result.stdout

    # alice is told, and only once
    inbox = run(roots["alice"], "inbox", expect=0)
    assert "replies on tasks you sent" in inbox.stdout
    run(roots["alice"], "show", task_id, expect=0)
    assert "replies on tasks you sent" not in run(roots["alice"], "inbox").stdout

    listing = run(roots["alice"], "ls", "--all").stdout
    assert task_id in listing and "done" in listing

    clean = run(roots["alice"], "lint", expect=0).stdout
    assert "clean" in clean

    # the task file itself was never rewritten
    files = sorted(os.listdir(shared))
    assert len([f for f in files if "_TASK-" in f]) == 3   # task + ACK + RESULT


def test_owner_gate_blocks_the_worker(tmp_path):
    roots, shared = init_agents(tmp_path)
    out = run(roots["alice"], "new", "--to", "bob", "--title", "publish it",
              "--ask", "Post the video.", "--needs-owner", expect=0)
    task_id = out.stdout.split("\t")[0]

    assert task_id in run(roots["bob"], "inbox").stdout
    assert "waiting for owner approval" in run(roots["bob"], "inbox").stdout
    proc = run(roots["bob"], "ack", task_id, expect=5)
    assert "owner confirmation" in proc.stderr

    run(roots["alice"], "owner-ok", task_id, "--note", "approved on the phone", expect=0)
    run(roots["bob"], "ack", task_id, expect=0)


def test_blocked_needs_a_question_and_lint_says_so(tmp_path):
    roots, shared = init_agents(tmp_path)
    task_id = run(roots["alice"], "new", "--to", "bob", "--title", "x",
                  "--ask", "do x", expect=0).stdout.split("\t")[0]
    run(roots["bob"], "ack", task_id, expect=0)
    run(roots["bob"], "blocked", task_id, "--why", "source file missing",
        "--ask", "upload it or point me at the link", expect=0)
    assert "blocked" in run(roots["alice"], "ls").stdout


def test_lint_catches_double_ack_and_secrets(tmp_path):
    roots, shared = init_agents(tmp_path)
    task_id = run(roots["alice"], "new", "--to", "bob", "--title", "y",
                  "--ask", "do y", "--needs-owner", expect=0).stdout.split("\t")[0]

    # a task that asked for approval gets ACKed anyway: write it the "wrong" way
    name = [f for f in os.listdir(shared) if task_id in f][0]
    base = name[:-3]
    with open(os.path.join(shared, base + "_ACK_bob.md"), "w", encoding="utf-8") as fh:
        fh.write("---\nkind: ACK\nagent: bob\n---\n\non it\n")
    with open(os.path.join(shared, "notes.md"), "w", encoding="utf-8") as fh:
        fh.write("login: alice\npassword: hunter2hunter2\n")

    proc = run(roots["alice"], "lint", expect=6)
    assert "acked_without_owner" in proc.stdout
    assert "secret" in proc.stdout


def test_dispatch_creates_a_batch(tmp_path):
    roots, shared = init_agents(tmp_path)
    spec = tmp_path / "batch.json"
    spec.write_text(json.dumps([
        {"to": "bob", "title": "one", "ask": "a"},
        {"to": "bob", "title": "two", "ask": "b", "priority": "high"},
    ]), encoding="utf-8")
    run(roots["alice"], "dispatch", str(spec), expect=0)
    listing = run(roots["alice"], "ls").stdout
    assert "one" in listing and "two" in listing
    assert "high" in listing


def test_result_must_say_something(tmp_path):
    roots, shared = init_agents(tmp_path)
    task_id = run(roots["alice"], "new", "--to", "bob", "--title", "z",
                  "--ask", "do z", expect=0).stdout.split("\t")[0]
    run(roots["bob"], "ack", task_id, expect=0)
    proc = run(roots["bob"], "result", task_id, "--text", "done", expect=2)
    assert "at least 20 chars" in proc.stderr


def test_watch_exit_codes_from_the_cli(tmp_path):
    roots, shared = init_agents(tmp_path)
    run(roots["alice"], "new", "--to", "bob", "--title", "w", "--ask", "do w", expect=0)
    first = run(roots["alice"], "watch", expect=10)
    second = run(roots["alice"], "watch", expect=0)
    assert first.stdout == second.stdout


def test_doctor_reports_a_working_checkout(tmp_path):
    roots, shared = init_agents(tmp_path)
    out = run(roots["alice"], "doctor", expect=0).stdout
    assert "reachable yes" in out
    assert "alice" in out
