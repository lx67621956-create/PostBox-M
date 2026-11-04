"""Onboarding surface: what a stranger needs to get started without Google Drive."""
import json
import os

from test_cli import REPO, init_agents, run


def test_providers_lists_a_no_google_path(tmp_path):
    roots, _shared = init_agents(tmp_path)
    proc = run(roots["alice"], "providers", expect=0)
    out = proc.stdout
    for preset in ("local", "webdav", "sftp", "gdrive"):
        assert preset in out
    # the China column must exist and mark gdrive as unusable there
    assert "IN CN" in out
    line = [l for l in out.splitlines() if l.startswith("gdrive")][0]
    assert "no" in line
    # and the local preset must not mention rclone as a requirement
    local = [l for l in out.splitlines() if l.startswith("local")][0]
    assert "nothing" in local


def test_providers_and_instructions_work_before_init(tmp_path):
    """A stranger must be able to ask 'which backend' before creating anything."""
    bare = str(tmp_path / "nothing-here")
    os.makedirs(bare)
    proc = run(bare, "providers", expect=0)
    assert "git" in proc.stdout and "local" in proc.stdout
    proc = run(bare, "instructions", "--lang", "zh", expect=0)
    assert "退出码" in proc.stdout


def test_providers_json_is_machine_readable(tmp_path):
    roots, _shared = init_agents(tmp_path)
    proc = run(roots["alice"], "providers", "--json", expect=0)
    data = json.loads(proc.stdout)
    assert isinstance(data, list) and len(data) >= 5
    for item in data:
        assert set(item) == {"preset", "cn", "needs", "what", "init"}
    assert [d for d in data if d["preset"] == "local"][0]["cn"] == "yes"


def test_instructions_cover_the_hard_rules(tmp_path):
    roots, _shared = init_agents(tmp_path)
    en = run(roots["alice"], "instructions", expect=0).stdout
    assert "postbox ack" in en and "exit 3" in en.lower()
    assert "no-artifact" in en
    assert "10 changed | 11" in en

    zh = run(roots["alice"], "instructions", "--lang", "zh", expect=0).stdout
    assert "退出码" in zh and "不许改任务文件" in zh
    assert "postbox owner-ok" in zh


def test_instructions_json(tmp_path):
    roots, _shared = init_agents(tmp_path)
    data = json.loads(run(roots["alice"], "instructions", "--json", expect=0).stdout)
    assert data["language"] == "en"
    assert data["text"].startswith("# PostBox-M")


def test_doctor_proves_write_access_and_cleans_up(tmp_path):
    roots, shared = init_agents(tmp_path)
    proc = run(roots["alice"], "doctor", expect=0)
    assert "reachable yes" in proc.stdout
    assert "writable  yes" in proc.stdout
    left = [n for n in os.listdir(shared) if "write-probe" in n]
    assert left == [], left


def test_delete_removes_and_reports_missing(tmp_path):
    from postbox.transport import LocalTransport
    t = LocalTransport(str(tmp_path / "box"))
    t.create("a.md", b"x")
    t.delete("a.md")
    assert not os.path.exists(str(tmp_path / "box" / "a.md"))
    try:
        t.delete("a.md")
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("deleting a missing file must raise FileNotFoundError")


def test_shipped_agents_md_matches_the_cli():
    """examples/AGENTS.md must not drift from `postbox instructions --lang zh`."""
    from postbox.cli import INSTRUCTIONS_ZH
    path = os.path.join(REPO, "examples", "AGENTS.md")
    text = open(path, encoding="utf-8").read().replace("\r\n", "\n").strip()
    assert text == INSTRUCTIONS_ZH.strip()
