from datetime import datetime, timedelta, timezone

from postbox import core


def test_slug_keeps_cjk_and_kills_path_separators():
    assert core.slug("小米") == "小米"
    assert core.slug("a/b\\c:d") == "a-b-c-d"
    assert core.slug("agent_a") == "agent-a"      # '_' separates event fields
    assert core.slug("  x  ") == "x"
    assert core.slug("") == "x"
    assert len(core.slug("x" * 200)) == 48


def test_task_id_and_filename_roundtrip(fixed_now):
    task_id = core.make_task_id("alice", "bob", fixed_now, 1)
    assert task_id == "20261102-0930-alice-to-bob-01"
    name = core.task_filename(task_id, "alice", "bob", "weekly-update", fixed_now)
    assert name == "2026-11-02_TASK-20261102-0930-alice-to-bob-01_alice-to-bob_weekly-update.md"

    text = core.render_task(task_id, "alice", "bob", "weekly-update", "do it",
                            created_at=core.fmt_ts(fixed_now))
    task = core.Task.parse(name, text)
    assert task is not None
    assert task.task_id == task_id
    assert (task.sender, task.recipient) == ("alice", "bob")
    assert task.title == "weekly-update"
    assert task.needs_owner is False


def test_event_naming_and_parsing(fixed_now):
    task_id = core.make_task_id("alice", "bob", fixed_now, 1)
    task_name = core.task_filename(task_id, "alice", "bob", "t", fixed_now)
    ack_name = core.event_filename(task_name, "ACK", "bob")
    assert ack_name == "2026-11-02_TASK-%s_alice-to-bob_t_ACK_bob.md" % task_id

    text = core.render_event("ACK", "bob", core.fmt_ts(fixed_now), "on it")
    event = core.Event.parse(ack_name, task_name, text)
    assert (event.kind, event.agent, event.seq) == ("ACK", "bob", 1)

    res2 = core.event_filename(task_name, "RESULT", "bob", 2)
    event2 = core.Event.parse(res2, task_name, core.render_event("RESULT", "bob", "x", "y"))
    assert (event2.kind, event2.seq) == ("RESULT", 2)


def test_event_tolerates_handwritten_labels(fixed_now):
    task_id = core.make_task_id("alice", "bob", fixed_now, 1)
    task_name = core.task_filename(task_id, "alice", "bob", "t", fixed_now)
    name = task_name.replace(".md", "_补充_bob.md")
    event = core.Event.parse(name, task_name, "just words")
    assert event.kind == "NOTE"
    assert event.agent == "bob"


def test_front_matter_crlf_bom_and_quotes():
    text = "\ufeff---\r\nid: x\r\nneeds_owner_confirm: \"yes\"\r\n---\r\nbody\r\n"
    meta, body = core.parse_front_matter(text)
    assert meta["id"] == "x"
    assert core.truthy(meta["needs_owner_confirm"]) is True
    assert body.strip() == "body"


def test_front_matter_unterminated_is_not_fatal():
    meta, body = core.parse_front_matter("---\nid: x\nno fence here")
    assert meta == {}
    assert body.startswith("---")


def test_route_split_both_separators():
    assert core.split_route("alice-to-bob") == ("alice", "bob")
    assert core.split_route("产品给研发") == ("产品", "研发")


def test_status_roundtrip():
    text = core.render_status("bob", "box", "idle", "none", "none", "-", "2026-11-02 09:30:00 +0800")
    assert len([l for l in text.splitlines() if l.strip()]) <= 10
    fields = core.parse_status(text)
    assert fields["agent"] == "bob"
    assert fields["state"] == "idle"


def test_timestamps_parse_with_and_without_offset():
    assert core.parse_ts("2026-11-02 09:30:00 +0800").utcoffset() == timedelta(hours=8)
    assert core.parse_ts("2026-11-02 09:30:00").hour == 9
    assert core.parse_ts("2026-11-02") is not None
    assert core.parse_ts("garbage") is None
