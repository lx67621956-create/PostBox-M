"""Transports: the only place that knows how bytes actually move.

The protocol needs exactly four operations — list, read, create-if-absent,
replace-own-file. Keeping that surface tiny is what lets the same tool run on
rclone (Google Drive), on a Dropbox/Syncthing/iCloud folder, or on a USB stick.

``create-if-absent`` is the concurrency primitive of the whole system: two
agents racing for the same task both try to create the same file, the loser
gets a conflict and backs off. See docs/design-notes.md.
"""
from __future__ import annotations

import hashlib
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
    md5: str = ""      # empty when the backend cannot provide one

    def as_line(self, with_hash: bool = False) -> str:
        if with_hash:
            return "%s|%d|%s|%s" % (self.name, self.size, self.mtime, self.md5 or "-")
        return "%s|%d|%s" % (self.name, self.size, self.mtime)


class Transport:
    kind = "abstract"

    def list(self, sub: str = "", recursive: bool = False,
             with_hash: bool = False) -> List[RemoteFile]:
        raise NotImplementedError

    def read(self, name: str) -> bytes:
        raise NotImplementedError

    def create(self, name: str, data: bytes) -> bool:
        """Create only if absent. Returns True when *our* bytes are now there."""
        raise NotImplementedError

    def replace(self, name: str, data: bytes) -> None:
        raise NotImplementedError

    def delete(self, name: str) -> None:
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

    def list(self, sub: str = "", recursive: bool = False,
             with_hash: bool = False) -> List[RemoteFile]:
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
                md5 = ""
                if with_hash:
                    with open(full, "rb") as fh:
                        md5 = hashlib.md5(fh.read()).hexdigest()
                out.append(RemoteFile(rel, st.st_size,
                                      time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(st.st_mtime)),
                                      md5=md5))
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

    def delete(self, name: str) -> None:
        try:
            os.remove(self._abs(name))
        except FileNotFoundError:
            raise FileNotFoundError(name) from None


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
    def list(self, sub: str = "", recursive: bool = False,
             with_hash: bool = False) -> List[RemoteFile]:
        import json
        cmd = ["lsjson", self._join(sub), "--files-only"]
        if recursive:
            cmd.append("-R")
        if with_hash:
            # Drive supplies md5Checksum natively; this is not an extra request
            # per file, only one more field in the same listing.
            cmd.append("--hash")
        proc = self._run(*cmd)
        try:
            rows = json.loads((proc.stdout or b"[]").decode("utf-8", "replace") or "[]")
        except ValueError as exc:
            raise TransportError("bad lsjson output: %s" % exc) from None
        out = [RemoteFile(r.get("Path", ""), int(r.get("Size") or 0),
                          r.get("ModTime", ""), r.get("ID", ""),
                          (r.get("Hashes") or {}).get("md5", ""))
               for r in rows]
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

    def delete(self, name: str) -> None:
        try:
            self._run("deletefile", self._join(name))
        except NotFound:
            raise FileNotFoundError(name) from None

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
class GitTransport(Transport):
    """A git repository as the mailbox — GitHub, Gitee, GitLab, or a bare repo on a VPS.

    A checkout is a normal working tree. Every write is one commit and one push;
    every listing starts with a rebase-pull. The protocol never edits a file after
    creation, so merges cannot conflict — the only race left is two agents creating
    the same name, and that is settled by whoever pushes first. The loser gets a
    ConflictError and backs off, exactly like the rclone backend.

    The reported mtime is `-` on purpose: a checkout's mtime changes on every clone
    and every pull, so it would make an unchanged mailbox look changed. The md5 is
    the file's content hash, which is stable across machines.
    """

    kind = "git"

    def __init__(self, root: str, git_bin: str = "git", remote: str = "origin",
                 branch: str = "", timeout: int = 60):
        self.root = os.path.abspath(root)
        self.git_bin = git_bin or "git"
        self.remote = remote or "origin"
        self.branch = branch
        self.timeout = timeout
        if not os.path.isdir(os.path.join(self.root, ".git")):
            raise TransportError(
                "%s is not a git checkout — clone the mailbox repo there first" % self.root)
        self._prepare_repo()

    # ---- plumbing -------------------------------------------------------
    def _git(self, *args, **kw):
        cmd = [self.git_bin, "-C", self.root] + [str(a) for a in args]
        env = os.environ.copy()
        env["GIT_TERMINAL_PROMPT"] = "0"     # never block on a password prompt
        env.setdefault("GIT_ASKPASS", "echo")
        try:
            return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", env=env,
                                  timeout=kw.get("timeout", self.timeout))
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise TransportError("git %s failed: %s" % (args[0], exc))

    def _check(self, proc, what):
        if proc.returncode != 0:
            raise TransportError("git %s failed (%d): %s"
                                 % (what, proc.returncode,
                                    (proc.stderr or proc.stdout).strip()[:300]))
        return proc

    def _prepare_repo(self) -> None:
        """Repo-local settings only — never touch the user's global git config."""
        for key, value in (("user.name", "postbox"), ("user.email", "postbox@localhost")):
            if not self._git("config", key).stdout.strip():
                self._git("config", key, value)
        # a mailbox is data: line endings must not be rewritten on checkout.
        if self._git("config", "core.autocrlf").stdout.strip().lower() != "false":
            self._git("config", "core.autocrlf", "false")
            # a clone made with autocrlf=true left CRLF in the tree while the index holds
            # LF. Rewrite the tree from the index, but only when that is the entire diff.
            dirty = self._git("diff", "--quiet").returncode != 0
            only_cr = self._git("diff", "--ignore-cr-at-eol", "--quiet").returncode == 0
            if dirty and only_cr:
                self._git("checkout", "--", ".")

    def _head(self) -> str:
        if self.branch:
            return self.branch
        proc = self._git("rev-parse", "--abbrev-ref", "HEAD")
        if proc.returncode == 0:
            branch = proc.stdout.strip()
            if branch and branch != "HEAD":
                return branch
        # a freshly initialised repo has no commit yet: ask the symbolic ref instead
        proc = self._git("symbolic-ref", "--short", "HEAD")
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip()
        raise TransportError("cannot determine the branch of %s" % self.root)

    def _pull(self) -> None:
        branch = self._head()
        proc = self._git("pull", "--rebase", "--quiet", self.remote, branch)
        if proc.returncode == 0:
            return
        msg = (proc.stderr or proc.stdout).strip()[:300]
        if "couldn't find remote ref" in msg or "no such ref" in msg:
            return                      # brand-new empty mailbox: nothing to pull yet
        self._git("rebase", "--abort")
        raise TransportError("git pull --rebase failed: %s" % msg)

    def _commit(self, message: str) -> None:
        self._git("add", "-A")
        proc = self._git("-c", "commit.gpgsign=false", "commit", "-q", "-m", message)
        if proc.returncode != 0 and "nothing to commit" not in (proc.stdout + proc.stderr):
            raise TransportError("git commit failed: %s"
                                 % (proc.stderr or proc.stdout).strip()[:300])

    def _push(self):
        branch = self._head()
        proc = self._git("push", "--quiet", self.remote, "HEAD:%s" % branch)
        return proc.returncode == 0, (proc.stderr or proc.stdout).strip()[:300]

    def _reset_to_remote(self) -> None:
        """Give up on our unpushed commit after losing a race."""
        branch = self._head()
        self._git("fetch", "--quiet", self.remote)
        self._git("reset", "--hard", "--quiet", "%s/%s" % (self.remote, branch))

    def _abs(self, name: str) -> str:
        name = name.replace("\\", "/").lstrip("/")
        target = os.path.normpath(os.path.join(self.root, name))
        if not (target == self.root or target.startswith(self.root + os.sep)):
            raise TransportError("path escapes mailbox root: %r" % name)
        return target

    # ---- transport surface ---------------------------------------------
    def list(self, sub: str = "", recursive: bool = False,
             with_hash: bool = False) -> List[RemoteFile]:
        self._pull()
        base = self._abs(sub) if sub else self.root
        out: List[RemoteFile] = []
        if not os.path.isdir(base):
            return out
        for dirpath, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d != ".git"]
            for name in files:
                full = os.path.join(dirpath, name)
                rel = os.path.relpath(full, self.root).replace("\\", "/")
                try:
                    with open(full, "rb") as fh:
                        data = fh.read()
                except OSError:
                    continue
                out.append(RemoteFile(name=rel, size=len(data), mtime="-",
                                      md5=hashlib.md5(data).hexdigest()))
            if not recursive:
                break
        out.sort(key=lambda f: f.name)
        return out

    def read(self, name: str) -> bytes:
        path = self._abs(name)
        try:
            with open(path, "rb") as fh:
                return fh.read()
        except OSError:
            # a miss may just mean "the other agent pushed since our last pull"
            self._pull()
            try:
                with open(path, "rb") as fh:
                    return fh.read()
            except OSError:
                raise FileNotFoundError(name) from None

    def exists(self, name: str) -> bool:
        return os.path.isfile(self._abs(name))

    def create(self, name: str, data: bytes) -> bool:
        self._pull()
        target = self._abs(name)
        if os.path.exists(target):
            raise ConflictError(name)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "wb") as fh:
            fh.write(data)
        self._commit("postbox: add %s" % name)
        ok, _err = self._push()
        if ok:
            return True
        # somebody pushed first; rebase, then find out who owns the name now
        proc = self._git("pull", "--rebase", "--quiet", self.remote, self._head())
        if proc.returncode != 0:
            self._git("rebase", "--abort")
            self._reset_to_remote()
            raise ConflictError(name)
        try:
            current = self.read(name)
        except FileNotFoundError:
            current = None
        if current != data:
            self._reset_to_remote()
            raise ConflictError(name)
        ok, err = self._push()
        if not ok:
            raise TransportError("git push failed after rebase: %s" % err)
        return True

    def replace(self, name: str, data: bytes) -> None:
        self._pull()
        target = self._abs(name)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "wb") as fh:
            fh.write(data)
        self._commit("postbox: update %s" % name)
        ok, _err = self._push()
        if ok:
            return
        proc = self._git("pull", "--rebase", "--quiet", self.remote, self._head())
        if proc.returncode != 0:
            self._git("rebase", "--abort")
            raise ConflictError(name)
        ok, err = self._push()
        if not ok:
            raise TransportError("git push failed after rebase: %s" % err)

    def delete(self, name: str) -> None:
        self._pull()
        target = self._abs(name)
        if not os.path.exists(target):
            raise FileNotFoundError(name)
        self._git("rm", "-q", "--", name)
        self._commit("postbox: remove %s" % name)
        ok, _err = self._push()
        if ok:
            return
        proc = self._git("pull", "--rebase", "--quiet", self.remote, self._head())
        if proc.returncode != 0:
            self._git("rebase", "--abort")
            raise ConflictError(name)
        ok, err = self._push()
        if not ok:
            raise TransportError("git push failed after rebase: %s" % err)


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
    if cfg.transport == "git":
        return GitTransport(cfg.resolve(cfg.path),
                            getattr(cfg, "git_bin", "") or "git",
                            getattr(cfg, "git_remote", "") or "origin",
                            getattr(cfg, "git_branch", "") or "")
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
