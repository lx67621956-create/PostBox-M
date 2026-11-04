"""The viewer is a view: it reads, it never writes, and it dies with the process."""
import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from postbox.config import Config
from postbox.serve import Handler, Snapshot
from test_cli import init_agents, run


def _start(root):
    cfg = Config.load(root)
    snapshot = Snapshot(cfg)
    handler = type("Bound", (Handler,), {"snapshot": snapshot,
                                         "page": b"<!doctype html><title>PostBox-M</title>"})
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, "http://127.0.0.1:%d" % httpd.server_address[1]


def _get(url, method="GET"):
    req = urllib.request.Request(url, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")


def test_state_endpoint_describes_the_mailbox(tmp_path):
    roots, _shared = init_agents(tmp_path)
    created = run(roots["alice"], "new", "--to", "bob", "--title", "看板上的任务",
                  "--ask", "把这件事做完", expect=0)
    task_id = created.stdout.split("\t")[0]
    run(roots["bob"], "ack", task_id, expect=0)
    run(roots["bob"], "status", "--heartbeat", expect=0)

    httpd, base = _start(roots["alice"])
    try:
        status, body = _get(base + "/api/state")
        data = json.loads(body)
    finally:
        httpd.shutdown()

    assert status == 200
    assert data["tasks"][0]["id"] == task_id
    assert data["tasks"][0]["state"] == "ack"
    assert data["tasks"][0]["title"] == "看板上的任务"
    assert {a["name"] for a in data["agents"]} == {"alice", "bob"}
    assert data["generated_at"]


def test_page_and_read_only_rules(tmp_path):
    roots, _shared = init_agents(tmp_path)
    httpd, base = _start(roots["alice"])
    try:
        page_status, page = _get(base + "/")
        post_status, _ = _get(base + "/api/state", method="POST")
        missing, _ = _get(base + "/nope")
    finally:
        httpd.shutdown()

    assert page_status == 200 and "PostBox-M" in page
    assert post_status == 405          # nothing in this thing can write
    assert missing == 404
