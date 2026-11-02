import os

import pytest

from postbox.transport import ConflictError, LocalTransport, RcloneTransport, TransportError


def test_local_create_is_exclusive(tmp_path):
    t = LocalTransport(str(tmp_path))
    assert t.create("a.md", b"one") is True
    with pytest.raises(ConflictError):
        t.create("a.md", b"two")
    assert t.read("a.md") == b"one"


def test_local_create_is_exclusive_even_for_identical_bytes(tmp_path):
    """Exclusive create is the lock. Identical bytes must still lose the race;
    idempotency (a retry after a timeout) is handled one level up, by the CLI."""
    t = LocalTransport(str(tmp_path))
    assert t.create("a.md", b"one") is True
    with pytest.raises(ConflictError):
        t.create("a.md", b"one")


def test_local_replace_is_atomic_and_rerunnable(tmp_path):
    t = LocalTransport(str(tmp_path))
    t.replace("STATUS_bob.md", b"v1")
    t.replace("STATUS_bob.md", b"v2")
    assert t.read("STATUS_bob.md") == b"v2"
    assert [f.name for f in t.list()] == ["STATUS_bob.md"]


def test_path_escape_is_refused(tmp_path):
    t = LocalTransport(str(tmp_path / "box"))
    (tmp_path / "box").mkdir()
    with pytest.raises(TransportError):
        t.read("../../etc/passwd")


def test_missing_file_raises_filenotfound(tmp_path):
    t = LocalTransport(str(tmp_path))
    with pytest.raises(FileNotFoundError):
        t.read("nope.md")
    assert t.exists("nope.md") is False


def test_rclone_spec_must_be_a_remote():
    with pytest.raises(TransportError):
        RcloneTransport("C:/local/folder")
    assert RcloneTransport("gdrive:agents/inbox")._join("a.md") == "gdrive:agents/inbox/a.md"


@pytest.mark.skipif(not os.environ.get("POSTBOX_TEST_REMOTE"),
                    reason="set POSTBOX_TEST_REMOTE=remote:folder to test a real backend")
def test_real_remote(tmp_path):
    """Opt-in smoke test against a throwaway remote folder.

    POSTBOX_TEST_REMOTE='gdrive:postbox-selftest-20260101' pytest tests/test_transport.py
    """
    import uuid
    spec = os.environ["POSTBOX_TEST_REMOTE"]
    t = RcloneTransport(spec, os.environ.get("RCLONE_BIN", "rclone"),
                        os.environ.get("RCLONE_CONFIG", ""))
    name = "selftest-%s.md" % uuid.uuid4().hex[:8]
    payload = "hello 中文\n".encode("utf-8")
    assert t.create(name, payload) is True
    assert t.read(name) == payload
    with pytest.raises(ConflictError):
        t.create(name, b"other")
    t.replace(name, payload + b"2")
    assert t.read(name) == payload + b"2"
    assert name in [f.name for f in t.list()]
    t.sync_to(str(tmp_path / "mirror"))
    assert (tmp_path / "mirror" / name).read_bytes() == payload + b"2"
