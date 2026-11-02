"""`postbox watch` — cheap, deterministic change detection for pollers.

Why this exists: an agent that polls a shared folder every five minutes can burn
a whole context window on "nothing new". The fix is to make the poller's output
*byte-identical* when nothing changed, so a supervisor (cron, systemd, an agent
harness) can diff stdout and skip the model entirely.

Three rules learned the hard way, encoded here:

1. **Never let an error overwrite the baseline.** Printing ``ERROR ...`` makes
   the recovery look like "every file is new" and floods the operator.
2. **Never silently replay the cache either.** Then a mailbox that is offline
   for a week looks perfectly healthy and nobody is paged.
   → replay the cache, but append one *constant* marker line after N consecutive
   failures, so exactly one wake-up happens per outage.
3. **The marker must not contain a timestamp**, or it differs every tick and the
   "one wake-up" becomes thousands.

Exit codes: 0 = unchanged (or suppressed blip), 10 = changed, 11 = degraded.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Dict, List, Optional, Tuple

from .transport import Transport, TransportError

DEGRADED_AFTER = 2                 # consecutive failures before we report
EXIT_FIRST = 10                    # no baseline yet: look once
MARK = "STATUS|DEGRADED|%s"
CHANGED = "CHANGED|+%d|-%d"
HEADER = "# postbox watch"


class WatchState:
    def __init__(self, state_dir: str):
        self.dir = state_dir
        self.path = os.path.join(state_dir, "watch.json")
        self.fails_path = os.path.join(state_dir, "watch_fails.txt")
        self.lines: List[str] = []
        self.paths: List[str] = []
        self.load()

    def load(self) -> None:
        try:
            with open(self.path, encoding="utf-8") as fh:
                data = json.load(fh)
            self.lines = list(data.get("lines") or [])
            self.paths = list(data.get("paths") or [])
        except (OSError, ValueError):
            self.lines, self.paths = [], []

    def save(self, lines: List[str], paths: List[str]) -> None:
        os.makedirs(self.dir, exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            json.dump({"lines": lines, "paths": paths}, fh, ensure_ascii=False, indent=0)
            fh.write("\n")
        os.replace(tmp, self.path)      # atomic: a crash never empties the baseline

    def bump_fail(self) -> int:
        n = self.fails()
        n += 1
        try:
            os.makedirs(self.dir, exist_ok=True)
            with open(self.fails_path, "w", encoding="utf-8") as fh:
                fh.write(str(n))
        except OSError:
            pass
        return n

    def fails(self) -> int:
        try:
            with open(self.fails_path, encoding="utf-8") as fh:
                return int((fh.read() or "0").strip() or 0)
        except (OSError, ValueError):
            return 0

    def clear_fails(self) -> None:
        try:
            os.remove(self.fails_path)
        except OSError:
            pass


def fingerprint(lines: List[str]) -> str:
    digest = hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()
    return digest[:16]


def collect(transport: Transport, paths: List[str], self_agent: str = "",
            prefix: str = "") -> Tuple[Optional[List[str]], str]:
    """Return (lines, error). One list call per watched path, never recursive.

    Lines carry an md5 (v1.1): same name, same size, changed bytes must still be
    a change. Our own STATUS file is frozen to `<name>|self` so the heartbeat
    we write every hour does not wake us up.
    """
    lines: List[str] = []
    own = "status_%s.md" % self_agent.lower() if self_agent else ""
    for path in paths or ["."]:
        sub = "" if path in (".", "./", "") else path.strip("/")
        try:
            files = transport.list(sub, with_hash=True)
        except FileNotFoundError:
            continue                        # a watch path that is not there yet
        except TransportError as exc:
            if "not found" in str(exc).lower() and not sub:
                continue
            return None, "%s: %s" % (sub or ".", str(exc)[:200])
        except Exception as exc:                                  # noqa: BLE001
            return None, "%s: %s" % (sub or ".", exc)
        for item in files:
            name = item.name if not sub else sub + "/" + item.name
            base = name.split("/")[-1]
            if prefix and not base.startswith(prefix):
                continue
            if own and base.lower() == own:
                lines.append(base + "|self")
                continue
            lines.append("%s|%d|%s|%s" % (name, item.size, item.mtime, item.md5 or "-"))
    lines.sort()
    return lines, ""


def run(transport: Transport, paths: List[str], state_dir: str,
        empty_is_error: bool = True, self_agent: str = "",
        prefix: str = "") -> Tuple[int, str]:
    state = WatchState(state_dir)
    lines, error = collect(transport, paths, self_agent=self_agent, prefix=prefix)

    if lines is None:
        return _degraded(state, error or "unknown")

    if empty_is_error and not lines and state.lines:
        return _degraded(state, "empty_listing")

    state.clear_fails()
    fp = fingerprint(lines)
    missing = sum(1 for line in lines if line.endswith("|-"))
    out = [HEADER]
    if missing:
        out.append("HASH|missing|%d" % missing)      # be honest, stay deterministic
    out += lines + ["FP|" + fp]

    previous = state.lines
    if not previous:
        state.save(lines, paths)
        return (EXIT_FIRST if lines else 0), "\n".join(out) + "\n"
    added = [l for l in lines if l not in set(previous)]
    removed = [l for l in previous if l not in set(lines)]
    if added or removed:
        out.append(CHANGED % (len(added), len(removed)))
        out += ["+ " + l for l in added]
        out += ["- " + l for l in removed]
        state.save(lines, paths)
        return 10, "\n".join(out) + "\n"

    state.save(lines, paths)
    return 0, "\n".join(out) + "\n"


def _degraded(state: WatchState, reason: str) -> Tuple[int, str]:
    if not state.lines:
        # Nothing to replay: this is the only case where raw error text is right.
        return 11, "%s\n%s\n%s\n" % (HEADER, MARK % "no_baseline", "ERROR|" + reason)

    fails = state.bump_fail()
    out = [HEADER] + state.lines + ["FP|" + fingerprint(state.lines)]
    if fails >= DEGRADED_AFTER:
        out.append(MARK % "transport_unreachable")
        _log_error(state.dir, reason)
        return 11, "\n".join(out) + "\n"
    # Single blip: output stays byte-identical to the baseline, so no wake-up.
    _log_error(state.dir, "blip(%d): %s" % (fails, reason))
    return 0, "\n".join(out) + "\n"


def _log_error(state_dir: str, message: str) -> None:
    try:
        os.makedirs(state_dir, exist_ok=True)
        with open(os.path.join(state_dir, "watch_errors.log"), "a", encoding="utf-8") as fh:
            fh.write(time.strftime("%Y-%m-%dT%H:%M:%S") + "\t" + message + "\n")
    except OSError:
        pass
