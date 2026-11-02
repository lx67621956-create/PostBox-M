"""The mailbox: read the folder, derive task state, answer "what is mine?".

State is *derived*, never stored on the task file. A task's lifecycle is the
ordered set of immutable event files that follow it — the same thing a human
sees when the folder is opened in Google Drive, and the reason no agent can
corrupt another agent's record by rewriting a line.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

from . import core
from .core import Event, Task
from .transport import RemoteFile, Transport, TransportError

OPEN_STATES = ("new", "waiting_owner", "ack", "working", "question")


@dataclass
class Entry:
    """A task plus everything that happened to it."""
    task: Task
    events: List[Event]
    state: str
    updated: str

    @property
    def last_event(self) -> Optional[Event]:
        return self.events[-1] if self.events else None

    def events_of(self, kind: str) -> List[Event]:
        return [e for e in self.events if e.kind == kind]


def derive_state(task: Task, events: Iterable[Event]) -> str:
    state = "new"
    for event in sorted(events, key=lambda e: (e.mtime, e.path)):
        if event.kind == "ACK":
            state = "ack"
        elif event.kind == "NOTE":
            if state in ("ack", "working"):
                state = "working"
        elif event.kind == "BLOCKED":
            state = "blocked"
        elif event.kind == "QUESTION":
            state = "question"
        elif event.kind == "RESULT":
            state = "done"
            break
        elif event.kind == "OWNER_NO":
            state = "rejected"
        elif event.kind == "OWNER_OK":
            if state == "waiting_owner":
                state = "ack"
    if task.needs_owner and not any(e.kind == "OWNER_OK" for e in events):
        if state not in ("done", "rejected"):
            return "waiting_owner"
    return state


class Mailbox:
    """Local view of a shared folder.

    Reads always come from a local mirror refreshed with a single backend call,
    so listing a 200-file mailbox costs one round trip instead of 200.
    """

    def __init__(self, transport: Transport, mirror: str = "", cache: str = ""):
        self.transport = transport
        self.mirror = os.path.abspath(mirror) if mirror else ""
        self.cache = cache
        self.files: List[RemoteFile] = []
        self.entries: List[Entry] = []
        self.by_id: Dict[str, Entry] = {}
        self.states: Dict[str, str] = {}

    # -- loading ---------------------------------------------------------
    def sync(self) -> "Mailbox":
        if self.mirror and self.transport.kind != "local":
            self.transport.sync_to(self.mirror)
        self.files = self._walk()
        self._parse()
        return self

    def _walk(self) -> List[RemoteFile]:
        if not self.mirror or self.transport.kind == "local":
            return self.transport.list()
        out: List[RemoteFile] = []
        for dirpath, _dirs, names in os.walk(self.mirror):
            for name in names:
                full = os.path.join(dirpath, name)
                rel = os.path.relpath(full, self.mirror).replace("\\", "/")
                st = os.stat(full)
                out.append(RemoteFile(rel, st.st_size,
                                      core_timestamp(st.st_mtime)))
        out.sort(key=lambda f: f.name)
        return out

    def _read_text(self, name: str) -> str:
        if self.mirror and self.transport.kind != "local":
            path = os.path.join(self.mirror, name.replace("/", os.sep))
            if not os.path.isfile(path):
                return ""
            with open(path, "rb") as fh:
                return fh.read().decode("utf-8", "replace")
        try:
            return self.transport.read(name).decode("utf-8", "replace")
        except (FileNotFoundError, TransportError):
            return ""

    def _parse(self) -> None:
        # Pass 1: which files are tasks? A name can look like a task but be an
        # event ("..._weekly_ACK_bob.md" matches the task regex too), and a
        # hand-written note can look like anything. The front matter decides:
        # a task declares its own id (or a from/to route).
        candidates = []
        for rf in self.files:
            name = rf.name.split("/")[-1]
            if not name.endswith(core.MD) or name.startswith("STATUS_"):
                continue
            if core.TASK_RE.match(name) is None:
                continue
            meta, _body = core.parse_front_matter(self._read_text(rf.name))
            if "id" in meta or ("from" in meta and "to" in meta):
                candidates.append(rf)
        cand_names = {rf.name for rf in candidates}
        task_files = []
        for rf in candidates:
            base = rf.name[:-len(core.MD)]
            if any(other.name != rf.name and base.startswith(other.name[:-len(core.MD)] + "_")
                   for other in candidates):
                continue                     # it is an event hanging off another task
            task_files.append(rf)

        tasks: List[Task] = []
        for rf in task_files:
            text = self._read_text(rf.name)
            task = Task.parse(rf.name.split("/")[-1], text)
            if task is None:
                continue
            task.size = rf.size
            task.mtime = rf.mtime
            tasks.append(task)

        bases = sorted((t.path for t in tasks), key=len, reverse=True)
        events: Dict[str, List[Event]] = {t.path: [] for t in tasks}
        for rf in self.files:
            name = rf.name.split("/")[-1]
            if not name.endswith(core.MD) or name.startswith("STATUS_"):
                continue
            owner = next((b for b in bases if name.startswith(b[:-len(core.MD)] + "_")), None)
            if owner is None:
                continue
            text = self._read_text(rf.name)
            event = Event.parse(name, owner, text)
            event.size = rf.size
            event.mtime = rf.mtime
            events[owner].append(event)
        self.entries = []
        for task in tasks:
            evs = sorted(events.get(task.path, []), key=lambda e: (e.mtime, e.path))
            state = derive_state(task, evs)
            updated = max([task.mtime] + [e.mtime for e in evs])
            self.entries.append(Entry(task, evs, state, updated))
        self.entries.sort(key=lambda e: (e.task.date, e.task.task_id))
        self.by_id = {e.task.task_id: e for e in self.entries}
        self.states = {e.task.task_id: e.state for e in self.entries}

    # -- queries ---------------------------------------------------------
    def get(self, task_id: str) -> Entry:
        entry = self.by_id.get(task_id) or self._match(task_id)
        if entry is None:
            raise KeyError("unknown task id: %s" % task_id)
        return entry

    def _match(self, fragment: str) -> Optional[Entry]:
        hits = [e for e in self.entries if fragment in e.task.task_id]
        return hits[0] if len(hits) == 1 else None

    def statuses(self) -> Dict[str, Dict[str, str]]:
        out: Dict[str, Dict[str, str]] = {}
        for rf in self.files:
            name = rf.name.split("/")[-1]
            if name.startswith("STATUS_") and name.endswith(core.MD):
                out[name[len("STATUS_"):-len(core.MD)]] = core.parse_status(self._read_text(rf.name))
        return out

    def pending_for(self, agent: str) -> List[Entry]:
        out = []
        for entry in self.entries:
            if entry.task.recipient != agent:
                continue
            if entry.state in ("done", "rejected"):
                continue
            out.append(entry)
        return out

    def replies_for(self, agent: str) -> List[Entry]:
        out = []
        for entry in self.entries:
            if entry.task.sender != agent:
                continue
            last = entry.last_event
            if last is None or last.agent in (agent, "?"):
                continue
            out.append(entry)
        return out


def core_timestamp(epoch: float) -> str:
    import time
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(epoch))


# --------------------------------------------------------------------------
class Ledger:
    """Local memory of what this device already looked at, so `inbox` is quiet."""

    def __init__(self, path: str):
        self.path = path
        self.data: Dict[str, str] = {}
        try:
            with open(path, encoding="utf-8") as fh:
                self.data = json.load(fh)
        except (OSError, ValueError):
            self.data = {}

    def seen(self, task_id: str, marker: str) -> None:
        self.data[task_id] = marker

    def is_seen(self, task_id: str, marker: str) -> bool:
        return self.data.get(task_id) == marker

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(self.data, fh, ensure_ascii=False, indent=1, sort_keys=True)
        os.replace(tmp, self.path)
