"""The claim race: many workers, one task, exactly one winner."""
import json
import os
import subprocess
import sys
import threading

from postbox.transport import ConflictError, LocalTransport

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WINNERS = []


def test_only_one_thread_can_create_the_same_file(tmp_path):
    t = LocalTransport(str(tmp_path))
    wins, losses, barrier = [], [], threading.Barrier(12)

    def worker():
        barrier.wait()
        try:
            t.create("claim.md", b"mine")
            wins.append(1)
        except ConflictError:
            losses.append(1)

    threads = [threading.Thread(target=worker) for _ in range(12)]
    [th.start() for th in threads]
    [th.join() for th in threads]
    assert len(wins) == 1 and len(losses) == 11


def test_concurrent_ack_processes_have_one_winner(tmp_path):
    shared = tmp_path / "mailbox"
    roots = {}
    for name in ("alice", "bob"):
        root = str(tmp_path / name)
        os.makedirs(root)
        subprocess.run([sys.executable, "-m", "postbox", "--root", root, "init",
                        "--path", str(shared), "--agent", name],
                       check=True, capture_output=True,
                       env=dict(os.environ, PYTHONPATH=REPO))
        roots[name] = root
    out = subprocess.run([sys.executable, "-m", "postbox", "--root", roots["alice"],
                          "new", "--to", "bob", "--title", "race", "--ask", "go"],
                         check=True, capture_output=True, text=True,
                         env=dict(os.environ, PYTHONPATH=REPO))
    task_id = out.stdout.split("\t")[0]

    procs = [subprocess.Popen([sys.executable, "-m", "postbox", "--root", roots["bob"],
                               "--agent", "bob", "ack", task_id],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              env=dict(os.environ, PYTHONPATH=REPO))
             for _ in range(6)]
    codes = [p.wait() for p in procs]
    assert codes.count(0) == 1, codes
    assert codes.count(3) == 5, codes
    acks = [f for f in os.listdir(shared) if "_ACK_" in f]
    assert len(acks) == 1
