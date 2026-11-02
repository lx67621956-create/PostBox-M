"""Transports: the only place that knows how bytes actually move.

The protocol needs exactly four operations — list, read, create-if-absent,
replace-own-file. Keeping that surface tiny is what lets the same tool run on
rclone (Google Drive), on a Dropbox/Syncthing/iCloud folder, or on a USB stick.

``create-if-absent`` is the concurrency primitive of the whole system: two
agents racing for the same task both try to create the same file, the loser
gets a conflict and backs off. See docs/design-notes.md.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from typing import List, Optional

RETRY_WAITS = (0, 5, 15, 45)  # last one only for rate limits
CALL_TIMEOUT = 60             # per rclone call; healthy calls are 1-10s
RATE_LIMIT_HINTS = ("quota exceeded", "ratelimitexceeded", "rate limit", "429")


class TransportError(RuntimeError):
    pass


class NotFound(TransportError):
    """The object (or its folder) is not there — never worth retrying."""


class ConflictError(TransportError):
    """The file already exists with different content."""


@dataclass
class RemoteFile:
    name: str          # POSIX-style path relative to the transport root
    size: int
    mtime: str         # ISO-8601 as reported by the backend
    file_id: str = ""

    def as_line(self) -> str:
        return "%s|%d|%s" % (self.name, self.size, self.mtime)


class Transport:
    kind = "abstract"

    def list(self, sub: str = "", recursive: bool = False) -> List[RemoteFile]:
        raise NotImplementedError

    def read(self, name: str) -> bytes:
        raise NotImplementedError

    def create(self, name: str, data: bytes) -> bool:
        """Create only if absent. Returns True when *our* bytes are now there."""
        raise NotImplementedError

    def replace(self, name: str, data: bytes) -> None:
        raise NotImplementedError

    def exists(self, name: str) -> bool:
        try:
            self.read(name)
            return True
        except FileNotFoundError:
            return False

    def mkdir(self, sub: str) -> None:
        pass

    def sync_to(self, local_dir: str) -> None:
        """Refresh a local mirror of the whole mailbox in one backend call."""
        pass


# --------------------------------------------------------------------------
class LocalTransport(Transport):
    """A plain directory — works with any folder-sync product or a shared NFS."""

    kind = "local"

    def __init__(self, root: str):
        self.root = os.path.abspath(root)

    def _abs(self, name: str) -> str:
        name = name.replace("\\", "/").lstrip("/")
        target = os.path.normpath(os.path.join(self.root, name))
        if not (target == self.root or target.startswith(self.root + os.sep)):
            raise TransportError("path escapes mailbox root: %r" % name)
        return target

    def list(self, sub: str = "", recursive: bool = False) -> List[RemoteFile]:
        base = self._abs(sub) if sub else self.root
        out: List[RemoteFile] = []
        if not os.path.isdir(base):
            return out
        if recursive:
            walker = os.walk(base)
        else:
            walker = [(base, [], [n for n in os.listdir(base)
                                  if os.path.isfile(os.path.join(base, n))])]
        for dirpath, _dirs, files in walker:
            for name in files:
                full = os.path.join(dirpath, name)
                rel = os.path.relpath(full, self.root).replace("\\", "/")
                st = os.stat(full)
                out.append(RemoteFile(rel, st.st_size,
                                      time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(st.st_mtime))))
        out.sort(key=lambda f: f.name)
        return out

    def read(self, name: str) -> bytes:
        path = self._abs(name)
        try:
            with open(path, "rb") as fh:
                return fh.read()
        except FileNotFoundError:
            raise FileNotFoundError(name) from None

    def create(self, name: str, data: bytes) -> bool:
        path = self._abs(name)
        os.makedirs(os.path.dirname(path) or self.root, exist_ok=True)
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0))
        except FileExistsError:
            raise ConflictError(name) from None
        try:
            os.write(fd, data)
        finally:
            os.close(fd)
        return True

    def replace(self, name: str, data: bytes) -> None:
        path = self._abs(name)
        os.makedirs(os.path.dirname(path) or self.root, exist_ok=True)
        tmp = path + ".tmp-" + str(os.getpid())
        with open(tmp, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)

    def mkdir(self, sub: str) -> None:
        os.makedirs(self._abs(sub), exist_ok=True)


# --------------------------------------------------------------------------
class RcloneTransport(Transport):
    """Google Drive / OneDrive / S3 … through rclone, no OAuth code in this repo.

    Cost note: list a *specific* folder, never the whole drive. Recursively
    listing a real 100-file shared drive takes 20-90s and regularly trips the
    Drive rate limiter; a single folder is ~2s.
    """

    kind = "rclone"

    def __init__(self, spec: str, binary: str = "rclone", config: str = "",
                 timeout: int = CALL_TIMEOUT):
        if not spec or ":" not in spec or re.match(r"^[A-Za-z]:[/\\]", spec):
            raise TransportError(
                "rclone spec must look like 'remote:folder', got %r" % spec)
        self.spec = spec.rstrip("/")
        self.binary = binary or "rclone"
        self.config = config
        self.timeout = timeout
        self.settle = float(os.environ.get("POSTBOX_SETTLE", "0.4"))

    # -- plumbing --------------------------------------------------------
    def _args(self, *cmd: str) -> List[str]:
        base = [self.binary] + list(cmd)
        if self.config:
            base += ["--config", self.config]
        return base + ["--log-level", "ERROR", "--retries", "1", "--low-level-retries", "2"]

    def _run(self, *cmd: str, timeout: Optional[int] = None) -> subprocess.CompletedProcess:
        args = self._args(*cmd)
        last = ""
        rate_limited = False
        for wait in RETRY_WAITS:
            if wait == RETRY_WAITS[-1] and not rate_limited:
                break                     # the 45s crawl is for quotas only
            if wait:
                time.sleep(wait)
            try:
                proc = subprocess.run(args, capture_output=True,
                                      timeout=timeout or self.timeout)
            except FileNotFoundError as exc:
                raise TransportError("rclone not found: %s" % exc) from None
            except subprocess.TimeoutExpired:
                last = "timeout after %ss" % (timeout or self.timeout)
                continue
            if proc.returncode == 0:
                return proc
            stderr = (proc.stderr or b"").decode("utf-8", "replace").strip()
            if proc.returncode in (3, 4):
                # rclone: 3 = directory not found, 4 = file not found.
                # Retrying "missing" costs 20s and never helps.
                raise NotFound(stderr[:300])
            last = stderr[:400] or "rc=%d" % proc.returncode
            rate_limited = any(hint in stderr.lower() for hint in RATE_LIMIT_HINTS)
        raise TransportError("rclone failed: %s" % last)

    def _join(self, name: str) -> str:
        return self.spec + "/" + name.replace("\\", "/").lstrip("/") if name else self.spec

    # -- api -------------------------------------------------------------
    def list(self, sub: str = "", recursive: bool = False) -> List[RemoteFile]:
        import json
        cmd = ["lsjson", self._join(sub), "--files-only"]
        if recursive:
            cmd.append("-R")
        proc = self._run(*cmd)
        try:
            rows = json.loads((proc.stdout or b"[]").decode("utf-8", "replace") or "[]")
        except ValueError as exc:
            raise TransportError("bad lsjson output: %s" % exc) from None
        out = [RemoteFile(r.get("Path", ""), int(r.get("Size") or 0),
                          r.get("ModTime", ""), r.get("ID", "")) for r in rows]
        out.sort(key=lambda f: f.name)
        return out

    def read(self, name: str) -> bytes:
        try:
            proc = self._run("cat", self._join(name))
        except NotFound:
            raise FileNotFoundError(name) from None
        return proc.stdout or b""

    def exists(self, name: str) -> bool:
        parts = name.split("/")
        try:
            files = self.list("/".join(parts[:-1]))
        except NotFound:
            return False
        return any(f.name.split("/")[-1] == parts[-1] for f in files)

    def create(self, name: str, data: bytes) -> bool:
        """Create-if-absent, best effort.

        Object storage has no atomic create: Drive happily overwrites a name.
        So we (1) refuse early when the name is taken, (2) write, (3) wait a
        short settle window, (4) verify the bytes that are actually there.
        That shrinks the race to the window between the check and the write and
        makes every loser detect the loss. It is not a mutex — one owner per
        task is the protocol rule that makes this safe (docs/design-notes.md).
        """
        if self.exists(name):
            raise ConflictError(name)
        tmp = _spill(data)
        try:
            self._run("copyto", tmp, self._join(name))
        finally:
            _unlink(tmp)
        if self.settle:
            time.sleep(self.settle)
        return self._verify(name, data)

    def replace(self, name: str, data: bytes) -> None:
        tmp = _spill(data)
        try:
            self._run("copyto", tmp, self._join(name))
        finally:
            _unlink(tmp)
        self._verify(name, data)

    def _verify(self, name: str, expect: bytes) -> bool:
        """Drive can 404 a file it just accepted, for a second or so."""
        for attempt in range(4):
            try:
                current = self.read(name)
            except FileNotFoundError:
                time.sleep(0.7)
                continue
            if current != expect:
                raise ConflictError(name)
            return True
        raise TransportError("wrote %s but it was still unreadable after retries" % name)

    def mkdir(self, sub: str) -> None:
        self._run("mkdir", self._join(sub))

    def sync_to(self, local_dir: str) -> None:
        """One round trip for the whole folder — never one call per file.

        A full recursive listing of a busy shared drive costs 20-90s and trips
        the rate limiter; `sync` of a markdown-only mailbox is a couple of
        seconds and gives us content, sizes and mtimes at once.
        """
        os.makedirs(local_dir, exist_ok=True)
        self._run("sync", self.spec, local_dir, timeout=max(self.timeout, 180))


# --------------------------------------------------------------------------
def _spill(data: bytes) -> str:
    fd, path = tempfile.mkstemp(prefix="postbox-", suffix=".tmp")
    try:
        os.write(fd, data)
    finally:
        os.close(fd)
    return path


def _unlink(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def build(cfg) -> Transport:
    if cfg.transport == "rclone":
        binary = cfg.rclone_bin or os.environ.get("POSTBOX_RCLONE_BIN") or "rclone"
        config = cfg.rclone_config or os.environ.get("POSTBOX_RCLONE_CONFIG") or ""
        if not (os.path.isabs(binary) or which_rclone()):
            raise TransportError(
                "rclone is not on PATH; set rclone_bin in .postbox/config.json "
                "(or POSTBOX_RCLONE_BIN) to the full path")
        return RcloneTransport(cfg.remote, binary, config)
    return LocalTransport(cfg.resolve(cfg.path))


def which_rclone() -> Optional[str]:
    return shutil.which("rclone")
