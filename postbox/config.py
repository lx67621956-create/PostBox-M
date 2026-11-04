"""Per-checkout configuration (``.postbox/config.json``).

Kept as JSON on purpose: tomllib only exists on 3.11+, and this project has a
hard zero-dependency rule so it can be dropped into any agent sandbox.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

CONFIG_DIR = ".postbox"
CONFIG_NAME = "config.json"

DEFAULTS: Dict[str, Any] = {
    "protocol_version": 1,
    "transport": "local",          # "local" | "rclone"
    "path": "shared",              # local transport: folder on disk
    "remote": "",                  # rclone transport: e.g. "gdrive:team/inbox"
    "rclone_bin": "rclone",
    "rclone_config": "",           # optional --config for rclone
    "git_bin": "git",
    "git_remote": "origin",
    "git_branch": "",
    "agent": "agent-a",
    "device": "",
    "utc_offset_hours": 8.0,
    "watch_paths": [".", "STATUS"],
    "sla_hours": 48,
    "state_dir": "",
}


@dataclass
class Config:
    protocol_version: int = 1
    transport: str = "local"
    path: str = "shared"
    remote: str = ""
    rclone_bin: str = "rclone"
    rclone_config: str = ""
    git_bin: str = "git"
    git_remote: str = "origin"
    git_branch: str = ""
    agent: str = "agent-a"
    device: str = ""
    utc_offset_hours: float = 8.0
    watch_paths: List[str] = field(default_factory=lambda: ["."])
    sla_hours: int = 48
    state_dir: str = ""
    root: str = ""                 # directory holding .postbox/ (not persisted)

    # ---- io -------------------------------------------------------------
    @classmethod
    def load(cls, start: str = ".") -> "Config":
        root = find_root(start)
        if root is None:
            raise FileNotFoundError(
                "no .postbox/config.json found (run `postbox init` first)")
        with open(os.path.join(root, CONFIG_DIR, CONFIG_NAME), encoding="utf-8") as fh:
            data = json.load(fh)
        cfg = cls()
        for key, value in data.items():
            if hasattr(cfg, key):
                setattr(cfg, key, value)
        cfg.root = root
        return cfg

    def save(self) -> str:
        root = self.root or os.getcwd()
        os.makedirs(os.path.join(root, CONFIG_DIR), exist_ok=True)
        path = os.path.join(root, CONFIG_DIR, CONFIG_NAME)
        payload = {k: v for k, v in asdict(self).items() if k != "root"}
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=True)
            fh.write("\n")
        return path

    # ---- derived --------------------------------------------------------
    def resolve(self, p: str) -> str:
        """Resolve a config-relative path against the checkout root."""
        if not p:
            return ""
        if os.path.isabs(p) or (len(p) > 1 and p[1] == ":"):
            return p
        return os.path.normpath(os.path.join(self.root or ".", p))

    @property
    def state_path(self) -> str:
        if self.state_dir:
            return self.resolve(self.state_dir)
        base = os.environ.get("POSTBOX_STATE") or os.path.join(
            os.path.expanduser("~"), ".cache", "postbox")
        return os.path.join(base, "watch-" + _slug("%s-%s" % (self.remote or self.path or "default",
                                                              self.agent)))

    @property
    def ident(self) -> str:
        return self.device or "unset"


def find_root(start: str = ".") -> Optional[str]:
    cur = os.path.abspath(start)
    while True:
        if os.path.isfile(os.path.join(cur, CONFIG_DIR, CONFIG_NAME)):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            return None
        cur = parent


def _slug(text: str) -> str:
    keep = []
    for ch in str(text):
        if ch.isalnum() or ch in "-_.@":
            keep.append(ch)
    return "".join(keep)[:40] or "default"
