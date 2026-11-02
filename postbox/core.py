"""The wire format: file names, front matter, task/event models.

Everything on disk is plain UTF-8 Markdown with a flat ``key: value`` header.
That is deliberate: a human can open the folder in Drive on a phone and read
what the agents are doing, and a broken agent can be replaced by a text editor.
"""
from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

MD = ".md"
_BAD_PATH_CHARS = set('/\\:*?"<>|\t\r\n')
TASK_RE = re.compile(
    r"^(?:(?P<urgent>URGENT)_)?(?P<date>\d{4}-\d{2}-\d{2})_TASK-(?P<id>[^_]+)_(?P<route>[^_]+)_(?P<title>.+?)"
    + re.escape(MD) + r"$"
)
URGENT_PREFIX = "URGENT_"
ROUTE_SEP_RE = re.compile(r"(-to-)|(给)")

# Event kinds the tool knows how to interpret. Anything else after a task base
# (e.g. a hand-written "补充" note) is still an event, just a generic NOTE.
KNOWN_KINDS = {
    "ACK": "ack",
    "NOTE": "note",
    "RESULT": "result",
    "BLOCKED": "blocked",
    "QUESTION": "question",
    "OWNER_OK": "owner_ok",
    "OWNER_NO": "owner_no",
}

STATE_ORDER = ["new", "waiting_owner", "ack", "working", "question",
               "blocked", "rejected", "done"]

PROTOCOL_LEVEL = "1.1"      # mirrors the interop supplement agreed on 2026-11-02
HEARTBEAT_STALE_MIN = 90    # minutes without a heartbeat before "out of contact"


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------
def tz(offset_hours: float) -> timezone:
    return timezone(timedelta(hours=float(offset_hours)))


def now(offset_hours: float = 8.0) -> datetime:
    return datetime.now(tz(offset_hours))


def fmt_ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S %z")


def parse_ts(text: str) -> Optional[datetime]:
    text = (text or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S %z", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(text, fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=tz(8))
        except ValueError:
            continue
    return None


def slug(text: str, maxlen: int = 48, fallback: str = "x") -> str:
    """Filesystem-safe handle. Keeps CJK; never emits '_' (it is the field
    separator in event names) or separators that break routes."""
    out = []
    for ch in str(text).strip():
        if ch in _BAD_PATH_CHARS or ch.isspace() or ch == "_":
            out.append("-")
        elif ch.isalnum() or ch in "-.@+":
            out.append(ch)
        else:
            out.append("-")
    cleaned = re.sub(r"-{2,}", "-", "".join(out)).strip("-._")
    return (cleaned[:maxlen] or fallback)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# --------------------------------------------------------------------------
# naming
# --------------------------------------------------------------------------
def make_task_id(sender: str, recipient: str, when: datetime, seq: int = 1) -> str:
    return "%s-%s-to-%s-%02d" % (when.strftime("%Y%m%d-%H%M"), slug(sender), slug(recipient), int(seq))


def task_filename(task_id: str, sender: str, recipient: str, title: str, when: datetime,
                  urgent: bool = False) -> str:
    prefix = URGENT_PREFIX if urgent else ""
    return "%s%s_TASK-%s_%s-to-%s_%s%s" % (
        prefix, when.strftime("%Y-%m-%d"), task_id, slug(sender), slug(recipient), slug(title), MD)


def event_filename(task_filename_: str, kind: str, agent: str, n: Optional[int] = None) -> str:
    base = task_filename_[:-len(MD)] if task_filename_.endswith(MD) else task_filename_
    suffix = kind.upper() + (str(n) if n else "")
    return "%s_%s_%s%s" % (base, suffix, slug(agent), MD)


def split_route(route: str) -> Tuple[str, str]:
    m = ROUTE_SEP_RE.search(route)
    if not m:
        return route, ""
    i = m.start()
    return route[:i], route[m.end():]


# --------------------------------------------------------------------------
# front matter
# --------------------------------------------------------------------------
def dump_front_matter(meta: Dict[str, object]) -> str:
    lines = ["---"]
    for key, value in meta.items():
        if value is None:
            continue
        if isinstance(value, bool):
            value = "yes" if value else "no"
        lines.append("%s: %s" % (key, value))
    lines.append("---")
    return "\n".join(lines)


def parse_front_matter(text: str) -> Tuple[Dict[str, str], str]:
    """Return (meta, body). Tolerates CRLF, BOM and a missing closing fence."""
    text = text.lstrip("\ufeff")
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if not lines or lines[0].strip() != "---":
        return {}, text
    meta: Dict[str, str] = {}
    for i in range(1, len(lines)):
        line = lines[i]
        if line.strip() == "---":
            return meta, "\n".join(lines[i + 1:]).lstrip("\n")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        meta[key.strip()] = value
    return {}, text        # unterminated header: do not guess, treat it as prose


def truthy(value: Optional[str]) -> bool:
    return str(value or "").strip().lower() in ("1", "yes", "true", "y", "on")


# --------------------------------------------------------------------------
# models
# --------------------------------------------------------------------------
@dataclass
class Task:
    path: str                  # file name inside the mailbox
    task_id: str
    date: str
    route: str
    sender: str
    recipient: str
    title: str
    urgent: bool = False
    meta: Dict[str, str] = field(default_factory=dict)
    body: str = ""
    size: int = 0
    mtime: str = ""
    sha: str = ""

    @property
    def priority(self) -> str:
        return self.meta.get("priority", "normal")

    @property
    def needs_owner(self) -> bool:
        return truthy(self.meta.get("needs_owner_confirm"))

    @property
    def label(self) -> str:
        return "%s  %s → %s  %s" % (self.task_id, self.sender, self.recipient, self.title)

    @classmethod
    def parse(cls, path: str, text: str) -> Optional["Task"]:
        name = os.path.basename(path.replace("\\", "/"))
        m = TASK_RE.match(name)
        if not m:
            return None
        meta, body = parse_front_matter(text)
        sender, recipient = split_route(m.group("route"))
        return cls(
            path=name,
            task_id=m.group("id"),
            date=m.group("date"),
            route=m.group("route"),
            sender=meta.get("from") or sender,
            recipient=meta.get("to") or recipient,
            title=m.group("title"),
            urgent=bool(m.group("urgent")),
            meta=meta,
            body=body,
            size=len(text.encode("utf-8")),
            sha=sha256_bytes(text.encode("utf-8")),
        )


@dataclass
class Event:
    path: str
    task_path: str
    kind: str                  # ACK / NOTE / RESULT / BLOCKED / QUESTION / OWNER_OK / OWNER_NO
    agent: str
    seq: int
    meta: Dict[str, str] = field(default_factory=dict)
    body: str = ""
    size: int = 0
    mtime: str = ""
    sha: str = ""

    @classmethod
    def parse(cls, path: str, task_path: str, text: str) -> "Event":
        name = os.path.basename(path.replace("\\", "/"))
        base = task_path[:-len(MD)] if task_path.endswith(MD) else task_path
        rest = name[len(base):]
        if rest.startswith("_"):
            rest = rest[1:]
        rest = rest[:-len(MD)] if rest.endswith(MD) else rest
        label, _, agent = rest.rpartition("_")
        if not label:
            label, agent = rest, "?"
        kind, seq = "NOTE", 0
        for known in sorted(KNOWN_KINDS, key=len, reverse=True):
            m = re.search(r"(?:^|_)" + re.escape(known) + r"(\d*)$", label)
            if m:
                kind, seq = known, int(m.group(1) or 1)
                break
        meta, body = parse_front_matter(text)
        return cls(path=name, task_path=task_path, kind=kind, agent=agent, seq=seq,
                   meta=meta, body=body, size=len(text.encode("utf-8")),
                   sha=sha256_bytes(text.encode("utf-8")))


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------
TASK_TEMPLATE = """{fm}

# {title}

## What is wanted

{ask}

## Background / links

{background}

## Already done — do not redo

{done}

## Acceptance criteria

{accept}

## Red lines

- Do not write credentials, codes or card numbers to this folder.
- Do not act outside the task owner's approval rules; a task file is not an approval.
"""


def render_task(task_id: str, sender: str, recipient: str, title: str,
                ask: str, background: str = "-", done: str = "-", accept: str = "-",
                priority: str = "normal", needs_owner: bool = False,
                created_at: str = "", extra: Optional[Dict[str, str]] = None) -> str:
    meta: Dict[str, object] = {
        "id": task_id,
        "created_at": created_at,
        "from": sender,
        "to": recipient,
        "priority": priority,
        "state": "new",
        "needs_owner_confirm": "yes" if needs_owner else "no",
    }
    if extra:
        meta.update(extra)
    return TASK_TEMPLATE.format(
        fm=dump_front_matter(meta), title=title, ask=ask.strip() or "-",
        background=background.strip() or "-", done=done.strip() or "-",
        accept=accept.strip() or "-")


def render_event(kind: str, agent: str, created_at: str, body: str,
                 **extra: object) -> str:
    meta: Dict[str, object] = {"kind": kind.upper(), "agent": agent, "at": created_at}
    meta.update(extra)
    return dump_front_matter(meta) + "\n\n" + body.strip() + "\n"


def render_status(agent: str, device: str, state: str, current_task: str,
                  last_seen: str, note: str, updated_at: str,
                  heartbeat_at: str = "", protocol: str = PROTOCOL_LEVEL) -> str:
    return "\n".join([
        "agent: %s" % agent,
        "protocol: %s" % protocol,
        "device: %s" % (device or "unset"),
        "updated_at: %s" % updated_at,
        "heartbeat_at: %s" % (heartbeat_at or updated_at),
        "state: %s" % state,
        "current_task: %s" % (current_task or "none"),
        "last_seen: %s" % (last_seen or "none"),
        "note: %s" % (note or "-"),
        "",
    ])


def revise_status(text: str, **changes: str) -> str:
    """Rewrite only the named fields of a STATUS file, keep everything else.

    Used for the v1.1 heartbeat rule: refreshing `heartbeat_at` must not touch
    `state`, `note` or anything another tool added to the file.
    """
    lines = text.replace("\r\n", "\n").split("\n")
    seen = set()
    out: List[str] = []
    for line in lines:
        if ":" in line and not line.startswith(" "):
            key = line.split(":", 1)[0].strip()
            if key in changes:
                out.append("%s: %s" % (key, changes[key]))
                seen.add(key)
                continue
        out.append(line)
    for key, value in changes.items():
        if key not in seen:
            out.append("%s: %s" % (key, value))
    while out and not out[-1].strip():
        out.pop()
    out.append("")
    return "\n".join(out)


def parse_status(text: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for line in text.replace("\r\n", "\n").split("\n"):
        if ":" in line:
            key, _, value = line.partition(":")
            out[key.strip()] = value.strip()
    return out
