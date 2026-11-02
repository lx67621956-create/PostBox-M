import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402


@pytest.fixture()
def mailbox(tmp_path):
    """A mailbox folder shared by two agent checkouts."""
    shared = tmp_path / "mailbox"
    shared.mkdir()
    return shared


@pytest.fixture()
def two_agents(tmp_path, mailbox):
    roots = {}
    for name in ("alice", "bob"):
        root = tmp_path / name
        root.mkdir()
        (root / ".postbox").mkdir()
        cfg = {
            "agent": name,
            "transport": "local",
            "path": str(mailbox).replace("\\", "/"),
            "device": name + "-box",
            "utc_offset_hours": 8,
        }
        import json
        (root / ".postbox" / "config.json").write_text(
            json.dumps(cfg), encoding="utf-8")
        roots[name] = str(root)
    return roots


@pytest.fixture()
def fixed_now():
    return datetime(2026, 11, 2, 9, 30, tzinfo=timezone(timedelta(hours=8)))
