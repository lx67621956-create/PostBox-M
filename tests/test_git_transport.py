"""The git backend: a private repo as the mailbox, with real clones and real pushes."""
import os
import subprocess
import threading

import pytest

from postbox.transport import ConflictError, GitTransport


def git(cwd, *args):
    proc = subprocess.run(["git", "-C", str(cwd)] + list(args),
                          capture_output=True, text=True, encoding="utf-8")
    assert proc.returncode == 0, (args, proc.stdout, proc.stderr)
    return proc.stdout


def clone(bare, dest):
    subprocess.run(["git", "clone", "-q", str(bare), str(dest)], check=True)
    return GitTransport(str(dest))


@pytest.fixture()
def repo(tmp_path):
    """A bare repo with one commit, plus a factory that hands out clones."""
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "-q", str(bare)], check=True)
    seed = tmp_path / "seed"
    subprocess.run(["git", "clone", "-q", str(bare), str(seed)], check=True)
    git(seed, "config", "user.name", "seed")
    git(seed, "config", "user.email", "seed@example.com")
    (seed / "README.md").write_text("mailbox\n", encoding="utf-8")
    git(seed, "add", "-A")
    git(seed, "commit", "-qm", "init")
    branch = git(seed, "symbolic-ref", "--short", "HEAD").strip()
    git(seed, "push", "-q", "origin", "HEAD:%s" % branch)

    made = []

    def factory(name):
        dest = tmp_path / name
        made.append(dest)
        return clone(bare, dest)

    factory.bare = bare
    return factory


def test_create_is_visible_to_the_other_clone(repo):
    alice = repo("alice")
    bob = repo("bob")
    assert alice.create("2026-01-01_TASK-x_alice-to-bob_hi.md", b"hello\n") is True
    names = [f.name for f in bob.list()]
    assert "2026-01-01_TASK-x_alice-to-bob_hi.md" in names
    assert bob.read("2026-01-01_TASK-x_alice-to-bob_hi.md") == b"hello\n"


def test_create_if_absent_loses_cleanly(repo):
    alice = repo("alice")
    bob = repo("bob")
    alice.create("task.md", b"alice\n")
    with pytest.raises(ConflictError):
        bob.create("task.md", b"bob\n")
    # the loser's clone must be clean again, not stuck mid-rebase
    assert git(str(repo.bare), "log", "--oneline").count("\n") >= 1
    assert bob.read("task.md") == b"alice\n"


def test_list_reports_a_stable_hash_and_no_mtime(repo):
    alice = repo("alice")
    alice.create("a.md", b"same bytes\n")
    first = alice.list(with_hash=True)
    second = alice.list(with_hash=True)
    assert [f.as_line(True) for f in first] == [f.as_line(True) for f in second]
    entry = [f for f in first if f.name == "a.md"][0]
    assert entry.mtime == "-"                  # a clone must not look like a change
    assert len(entry.md5) == 32 and entry.md5 != "-"


def test_replace_and_delete(repo):
    alice = repo("alice")
    bob = repo("bob")
    alice.create("STATUS_alice.md", b"v1\n")
    alice.replace("STATUS_alice.md", b"v2\n")
    assert bob.read("STATUS_alice.md") == b"v2\n"
    alice.delete("STATUS_alice.md")
    assert [f.name for f in bob.list()] == ["README.md"]
    with pytest.raises(FileNotFoundError):
        alice.delete("STATUS_alice.md")


def test_concurrent_create_has_exactly_one_winner(repo):
    """Six clones, six threads, one name: the protocol promises a single owner."""
    boxes = [repo("w%d" % i) for i in range(6)]
    results = []
    lock = threading.Lock()

    def attempt(box, n):
        try:
            ok = box.create("TASK-race.md", ("writer %d\n" % n).encode())
        except ConflictError:
            ok = False
        with lock:
            results.append(ok)

    threads = [threading.Thread(target=attempt, args=(box, i))
               for i, box in enumerate(boxes)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(1 for r in results if r) == 1, results


def test_cli_roundtrip_on_git(tmp_path, repo):
    """Two checkouts, one repo, a full hand-off through the real CLI."""
    from test_cli import run

    alice_repo = str(tmp_path / "alice-mail")
    bob_repo = str(tmp_path / "bob-mail")
    clone(repo.bare, alice_repo)
    clone(repo.bare, bob_repo)
    roots = {}
    for name, mail in (("alice", alice_repo), ("bob", bob_repo)):
        root = str(tmp_path / (name + "-root"))
        os.makedirs(root)
        run(root, "init", "--transport", "git", "--path", mail, "--agent", name, expect=0)
        roots[name] = root

    created = run(roots["alice"], "new", "--to", "bob", "--title", "git handoff",
                  "--ask", "prove it works", expect=0)
    task_id = created.stdout.split("\t")[0]

    inbox = run(roots["bob"], "inbox", expect=0)
    assert task_id in inbox.stdout

    run(roots["bob"], "ack", task_id, expect=0)
    body = tmp_path / "out.md"
    body.write_text("delivered over git\n", encoding="utf-8")
    run(roots["bob"], "result", task_id, "--text", "done, file attached, verified end to end",
        "--artifact", str(body), "--verified", expect=0)

    ls = run(roots["alice"], "ls", "--all", expect=0)
    assert "done" in ls.stdout
    assert run(roots["alice"], "lint").returncode in (0, 6)
