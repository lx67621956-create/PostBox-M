"""`postbox lint` — the reviewer that catches what agents quietly get wrong.

Every check here exists because it broke a real multi-agent mailbox at least
once: double RESULT files, events pointing at a task that was renamed, an ACK
written for a task that still needed owner approval, credentials pasted into a
shared folder, a STATUS file frozen three weeks ago while the agent was dead.
"""
from __future__ import annotations

import re
from typing import Dict, List, Tuple

from . import core
from .state import Entry, Mailbox

SECRET_PATTERNS: List[Tuple[str, "re.Pattern[str]"]] = [
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("aws_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("slack_token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    ("cn_id_card", re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")),
    ("assigned_secret", re.compile(
        r"(?i)\b(passwd|password|secret|token|api[_-]?key)\b\s*[:=]\s*[\"']?[A-Za-z0-9/+_-]{12,}")),
]


def scan_secrets(text: str) -> List[str]:
    hits = []
    for name, pattern in SECRET_PATTERNS:
        if pattern.search(text):
            hits.append(name)
    return hits


def lint(mailbox: Mailbox, sla_hours: int = 48, now=None) -> List[Tuple[str, str, str]]:
    """Return [(level, code, message)] — level is 'error' | 'warn'."""
    out: List[Tuple[str, str, str]] = []
    now = now or core.now()

    # 1. duplicate ids
    seen: Dict[str, List[str]] = {}
    for entry in mailbox.entries:
        seen.setdefault(entry.task.task_id, []).append(entry.task.path)
    for task_id, paths in seen.items():
        if len(paths) > 1:
            out.append(("error", "duplicate_id",
                        "%s exists %d times: %s" % (task_id, len(paths), ", ".join(paths))))

    # 2. events without a task
    bases = {e.task.path[:-len(core.MD)] for e in mailbox.entries}
    for rf in mailbox.files:
        name = rf.name.split("/")[-1]
        if not name.endswith(core.MD) or name.startswith("STATUS_"):
            continue
        if "_TASK-" in name and not any(name.startswith(b + "_") or name == b + core.MD for b in bases):
            out.append(("warn", "orphan_event",
                        "%s looks like an event but no task matches it" % name))

    for entry in mailbox.entries:
        # 3. two different agents claiming the same result
        results = entry.events_of("RESULT")
        agents = {e.agent for e in results}
        if len(agents) > 1:
            out.append(("error", "double_result",
                        "%s has RESULT from %s" % (entry.task.task_id, ", ".join(sorted(agents)))))
        if len(results) > 1 and len(agents) == 1:
            out.append(("warn", "repeated_result",
                        "%s has %d RESULT files from %s" % (entry.task.task_id, len(results),
                                                            next(iter(agents)))))

        # 4. work started without the approval the task asked for
        if entry.task.needs_owner and entry.events_of("ACK") and not entry.events_of("OWNER_OK"):
            out.append(("error", "acked_without_owner",
                        "%s needs owner confirmation but was ACKed anyway" % entry.task.task_id))

        # 5. "done" that says nothing
        for result in results:
            if len(result.body.strip()) < 20:
                out.append(("warn", "empty_result",
                            "%s RESULT by %s is under 20 chars — that is not a delivery"
                            % (entry.task.task_id, result.agent)))

        # 6. accepted but silently abandoned
        if entry.state in ("ack", "working", "question"):
            created = core.parse_ts(entry.task.meta.get("created_at", "")) or core.parse_ts(entry.task.date)
            if created is not None:
                age = (now - created).total_seconds() / 3600.0
                if age > sla_hours:
                    out.append(("warn", "stale_task",
                                "%s is %s after %dh (state=%s)"
                                % (entry.task.task_id, _human(age), sla_hours, entry.state)))

        # 7. sender forgot to be told
        if entry.state == "blocked" and not entry.events_of("QUESTION"):
            out.append(("warn", "blocked_no_question",
                        "%s is blocked but nobody was asked a question" % entry.task.task_id))

    # 8. frozen or missing status files
    statuses = mailbox.statuses()
    if not statuses:
        out.append(("warn", "no_status", "no STATUS_<agent>.md in the mailbox"))
    for agent, fields in statuses.items():
        updated = core.parse_ts(fields.get("updated_at", ""))
        if updated is None:
            out.append(("warn", "status_unparsable",
                        "STATUS_%s.md has no parsable updated_at" % agent))
            continue
        age = (now - updated).total_seconds() / 3600.0
        if age > max(sla_hours, 24):
            out.append(("warn", "stale_status",
                        "STATUS_%s.md is %s old (state=%s)" % (agent, _human(age), fields.get("state"))))
        if fields.get("state") in ("online", "idle") and age > 24:
            out.append(("error", "zombie_status",
                        "STATUS_%s.md claims %s but has not been refreshed for %s"
                        % (agent, fields.get("state"), _human(age))))

    # 9. secrets anywhere
    for rf in mailbox.files:
        if not rf.name.endswith(core.MD):
            continue
        text = mailbox._read_text(rf.name)
        hits = scan_secrets(text)
        if hits:
            out.append(("error", "secret",
                        "%s matches %s — rotate it and remove it from the folder"
                        % (rf.name, ", ".join(hits))))
    return out


def _human(hours: float) -> str:
    if hours >= 48:
        return "%.0f days" % (hours / 24)
    return "%.0f h" % hours
