"""Command line interface. `postbox --help` for the whole surface."""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import unicodedata
from datetime import timedelta
from typing import List, Optional

from . import __version__, core, i18n
from .config import Config
from .lint import lint
from .state import Entry, Ledger, Mailbox, derive_state
from .transport import ConflictError, TransportError, build
from .watch import run as watch_run

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_CONFLICT = 3
EXIT_NOTFOUND = 4
EXIT_NEEDS_OWNER = 5
EXIT_LINT = 6
EXIT_WATCH_CHANGED = 10
EXIT_WATCH_DEGRADED = 11


class Failure(Exception):
    def __init__(self, message: str, code: int = 1):
        super().__init__(message)
        self.code = code


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def mailbox(cfg: Config) -> Mailbox:
    transport = build(cfg)
    # only rclone needs a local mirror; a git checkout and a local folder are already local
    mirror = os.path.join(cfg.state_path, "mirror") if cfg.transport == "rclone" else ""
    box = Mailbox(transport, mirror=mirror, cache=cfg.state_path)
    box.sync()
    return box


def ledger(cfg: Config) -> Ledger:
    return Ledger(os.path.join(cfg.state_path, "inbox.json"))


def read_input(text: Optional[str], path: Optional[str], stdin_hint: str = "body") -> str:
    if path:
        if path == "-":
            return sys.stdin.read()
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    if text:
        if text == "-":
            return sys.stdin.read()
        return text
    if not sys.stdin.isatty():
        data = sys.stdin.read()
        if data.strip():
            return data
    raise Failure("nothing to write: pass --text/--file (or %s on stdin)" % stdin_hint, EXIT_USAGE)


def width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)


def pad(text: str, size: int) -> str:
    return text + " " * max(0, size - width(text))


def table(rows: List[List[str]], headers: List[str]) -> str:
    widths = [width(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], width(cell))
    out = ["  ".join(pad(h, widths[i]) for i, h in enumerate(headers)).rstrip(),
           "  ".join("-" * widths[i] for i in range(len(headers)))]
    for row in rows:
        out.append("  ".join(pad(c, widths[i]) for i, c in enumerate(row)).rstrip())
    return "\n".join(out)


def age_of(entry: Entry, offset_hours: float) -> str:
    stamp = core.parse_ts(entry.task.meta.get("created_at", "")) or core.parse_ts(entry.task.date)
    if stamp is None:
        return "?"
    hours = (core.now(offset_hours) - stamp).total_seconds() / 3600.0
    if hours < 1:
        return "%dm" % max(1, int(hours * 60))
    if hours < 48:
        return "%dh" % int(hours)
    return "%dd" % int(hours / 24)


def dump(entry: Entry) -> dict:
    return {
        "id": entry.task.task_id,
        "title": entry.task.title,
        "from": entry.task.sender,
        "to": entry.task.recipient,
        "state": entry.state,
        "priority": entry.task.priority,
        "needs_owner_confirm": entry.task.needs_owner,
        "created_at": entry.task.meta.get("created_at", ""),
        "updated": entry.updated,
        "file": entry.task.path,
        "events": [{"kind": e.kind, "agent": e.agent, "file": e.path, "at": e.mtime}
                   for e in entry.events],
    }


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------
def cmd_init(args) -> int:
    root = os.path.abspath(args.dir or args.root)
    os.makedirs(root, exist_ok=True)
    cfg_path = os.path.join(root, ".postbox", "config.json")
    if os.path.isfile(cfg_path) and not args.force:
        raise Failure("%s exists (use --force to rewrite)" % cfg_path, EXIT_CONFLICT)
    cfg = Config(root=root, transport=args.transport, path=args.path,
                 remote=args.remote,
                 agent=core.slug(getattr(args, "agent", "") or "agent-a"),
                 device=getattr(args, "device", ""),
                 rclone_bin=getattr(args, "rclone_bin", ""),
                 rclone_config=getattr(args, "rclone_config", ""),
                 git_bin=getattr(args, "git_bin", "") or "git",
                 git_branch=getattr(args, "git_branch", ""),
                 lang=(getattr(args, "lang", "") or os.environ.get("POSTBOX_LANG", "")))
    if args.transport == "rclone" and not args.remote:
        raise Failure("--transport rclone needs --remote, e.g. --remote gdrive:agents/inbox",
                      EXIT_USAGE)
    if args.transport == "git":
        target = cfg.resolve(cfg.path)
        clone_url = getattr(args, "clone", "") or ""
        if clone_url and not os.path.isdir(os.path.join(target, ".git")):
            parent = os.path.dirname(target)
            if parent:
                os.makedirs(parent, exist_ok=True)
            proc = subprocess.run([cfg.git_bin, "clone", "--quiet", clone_url, target],
                                  capture_output=True, text=True)
            if proc.returncode != 0:
                raise Failure("git clone failed: %s"
                              % (proc.stderr or proc.stdout).strip()[:300], EXIT_USAGE)
        if not os.path.isdir(os.path.join(target, ".git")):
            raise Failure(
                "--transport git needs a checkout: --clone https://gitee.com/you/inbox.git "
                "or --path to an existing clone", EXIT_USAGE)
    cfg.save()
    if args.transport == "local":
        os.makedirs(cfg.resolve(cfg.path), exist_ok=True)
    else:
        build(cfg).mkdir("")
    # a mailbox with a heartbeat file is a mailbox where `lint` has a baseline
    box = mailbox(cfg)
    if not box.statuses():
        cfg_bytes = core.render_status(cfg.agent, cfg.device, "online", "none", "none",
                                       "created by postbox init", core.fmt_ts(core.now(cfg.utc_offset_hours)))
        build(cfg).replace("STATUS_%s%s" % (core.slug(cfg.agent), core.MD),
                           cfg_bytes.encode("utf-8"))
    print(i18n.tpl("initialised %s", "已初始化 %s") % cfg_path)
    print(i18n.tpl("mailbox   %s", "邮箱      %s") % (cfg.remote or cfg.resolve(cfg.path)))
    print(i18n.tpl("agent     %s", "本机身份  %s") % cfg.agent)
    print(i18n.tpl('next      postbox new --to <peer> --title "..." --ask "..."',
                   '下一步    postbox new --to <对方> --title "..." --ask "..."'))
    return EXIT_OK


def cmd_new(args) -> int:
    cfg = args.cfg
    box = mailbox(cfg)
    sender = args.sender or cfg.agent
    when = core.now(cfg.utc_offset_hours)
    ask = read_input(args.ask, args.ask_file)
    body_title = args.title.strip()
    if not body_title:
        raise Failure("--title is required", EXIT_USAGE)
    for attempt in range(1, 20):
        seq = _next_seq(box, when, sender, args.to) + attempt - 1
        task_id = core.make_task_id(sender, args.to, when, seq)
        name = core.task_filename(task_id, sender, args.to, body_title, when,
                                  urgent=bool(getattr(args, "urgent", False)))
        text = core.render_task(
            task_id=task_id, sender=sender, recipient=args.to, title=body_title,
            ask=ask, background=args.background or "-", done=args.done or "-",
            accept=args.accept or "-", priority=args.priority,
            needs_owner=args.needs_owner, created_at=core.fmt_ts(when))
        try:
            box.transport.create(name, text.encode("utf-8"))
        except ConflictError:
            continue
        print("%s\t%s" % (task_id, name))
        if args.needs_owner:
            print("note: needs_owner_confirm=yes — the receiver must not start "
                  "until `postbox owner-ok %s` exists" % task_id, file=sys.stderr)
        return EXIT_OK
    raise Failure("could not allocate a task id (too many collisions)", EXIT_CONFLICT)


def _next_seq(box: Mailbox, when, sender: str, recipient: str) -> int:
    prefix = "%s-%s-to-%s-" % (when.strftime("%Y%m%d-%H%M"), core.slug(sender), core.slug(recipient))
    seqs = [int(e.task.task_id.rsplit("-", 1)[1]) for e in box.entries
            if e.task.task_id.startswith(prefix) and e.task.task_id.rsplit("-", 1)[1].isdigit()]
    return (max(seqs) + 1) if seqs else 1


def cmd_dispatch(args) -> int:
    with open(args.file, encoding="utf-8") as fh:
        items = json.load(fh)
    if isinstance(items, dict):
        items = items.get("tasks", [])
    if not isinstance(items, list):
        raise Failure("%s must contain a JSON array of tasks" % args.file, EXIT_USAGE)
    created = 0
    for item in items:
        if not item.get("to") or not item.get("title"):
            raise Failure("every task needs 'to' and 'title': %r" % item, EXIT_USAGE)
        ns = argparse.Namespace(
            cfg=args.cfg, to=item["to"], title=item["title"],
            ask=item.get("ask", "-"), ask_file=item.get("ask_file"),
            background=item.get("background"), done=item.get("done"),
            accept=item.get("accept"), priority=item.get("priority", "normal"),
            needs_owner=bool(item.get("needs_owner_confirm")),
            sender=item.get("from") or args.cfg.agent)
        cmd_new(ns)
        created += 1
    print("%d task(s) dispatched" % created, file=sys.stderr)
    return EXIT_OK


def cmd_ls(args) -> int:
    cfg = args.cfg
    box = mailbox(cfg)
    entries = box.entries
    if args.state:
        wanted = set(args.state.split(","))
        entries = [e for e in entries if e.state in wanted]
    if args.to:
        entries = [e for e in entries if e.task.recipient == args.to]
    if args.mine:
        entries = [e for e in entries if args.mine in (e.task.recipient, e.task.sender)]
    if not args.all:
        entries = [e for e in entries if e.state not in ("done", "rejected")]
    if args.json:
        print(json.dumps([dump(e) for e in entries], ensure_ascii=False, indent=2))
        return EXIT_OK
    if not entries:
        print("(empty)")
        return EXIT_OK
    rows = [[e.task.task_id, e.state, e.task.sender + "→" + e.task.recipient,
             e.task.priority, age_of(e, cfg.utc_offset_hours), e.task.title]
            for e in entries]
    print(table(rows, ["ID", "STATE", "ROUTE", "PRIO", "AGE", "TITLE"]))
    return EXIT_OK


def cmd_show(args) -> int:
    cfg = args.cfg
    box = mailbox(cfg)
    try:
        entry = box.get(args.task)
    except KeyError as exc:
        raise Failure(exc.args[0] if exc.args else str(exc), EXIT_NOTFOUND) from None
    if args.json:
        print(json.dumps(dump(entry), ensure_ascii=False, indent=2))
    else:
        task = entry.task
        print("id       %s" % task.task_id)
        print("state    %s  (updated %s)" % (entry.state, entry.updated))
        print("route    %s → %s" % (task.sender, task.recipient))
        print("priority %s%s" % (task.priority,
                                 "  needs_owner_confirm=yes" if task.needs_owner else ""))
        print("file     %s" % task.path)
        print("")
        print(task.body.rstrip() if task.body.strip() else "(no body)")
        if entry.events:
            print("")
            print("events:")
            for event in entry.events:
                print("  %-9s %-12s %s  %s" % (event.kind, event.agent, event.mtime, event.path))
            print("")
            for event in entry.events:
                if not event.body.strip():
                    continue
                print("--- %s by %s ---" % (event.kind, event.agent))
                print(event.body.rstrip())
                print("")
    led = ledger(cfg)
    led.seen(entry.task.task_id, entry.updated)
    led.save()
    return EXIT_OK


def cmd_inbox(args) -> int:
    cfg = args.cfg
    box = mailbox(cfg)
    me = args.agent or cfg.agent
    todo = box.pending_for(me)
    replies = box.replies_for(me)
    led = ledger(cfg)
    fresh = [e for e in replies if not led.is_seen(e.task.task_id, e.updated)]
    hold = [e for e in todo if e.state == "waiting_owner"]
    work = [e for e in todo if e.state != "waiting_owner"]
    if args.json:
        print(json.dumps({"todo": [dump(e) for e in work],
                          "blocked_by_owner": [dump(e) for e in hold],
                          "new_replies": [dump(e) for e in fresh]},
                         ensure_ascii=False, indent=2))
        return EXIT_OK
    if not work and not fresh and not hold:
        print(i18n.tpl("nothing for %s", "%s 这里没有待办") % me)
        return EXIT_OK
    if work:
        print("todo →")
        print(table([[e.task.task_id, e.state, e.task.sender, age_of(e, cfg.utc_offset_hours),
                      e.task.title] for e in work], ["ID", "STATE", "FROM", "AGE", "TITLE"]))
    if hold:
        print("\nwaiting for owner approval (do not start) →")
        print(table([[e.task.task_id, e.task.sender, e.task.title] for e in hold],
                    ["ID", "FROM", "TITLE"]))
    if fresh:
        print("\nreplies on tasks you sent →")
        last = [e.last_event for e in fresh]
        print(table([[e.task.task_id, (l.kind if l else "?"), (l.agent if l else "?"),
                      e.task.title] for e, l in zip(fresh, last)],
                    ["ID", "LAST", "BY", "TITLE"]))
    return EXIT_OK


def _event_name(entry: Entry, kind: str, agent: str, existing: List[str],
                unique: bool = False) -> str:
    base = core.event_filename(entry.task.path, kind, agent)
    if unique or base not in existing:
        # `unique` kinds (ACK, OWNER_OK/NO) may exist once per agent and task: racing
        # writers must collide on the same name so that create-if-absent picks a winner.
        return base
    for n in range(2, 100):
        candidate = core.event_filename(entry.task.path, kind, agent, n)
        if candidate not in existing:
            return candidate
    raise Failure("too many %s files for %s" % (kind, entry.task.task_id), EXIT_CONFLICT)


def _files(box: Mailbox) -> List[str]:
    return [f.name.split("/")[-1] for f in box.files]


def _write_event(cfg: Config, task_id: str, kind: str, body: str, agent: str,
                 extra: dict, gate: bool = False, status_state: str = "",
                 unique: bool = False) -> str:
    instance = "%d-%s" % (os.getpid(), socket.gethostname().split(".")[0][:24])
    box = mailbox(cfg)
    try:
        entry = box.get(task_id)
    except KeyError as exc:
        raise Failure(exc.args[0] if exc.args else str(exc), EXIT_NOTFOUND) from None
    if entry.state == "done" and kind not in ("NOTE", "OWNER_OK", "OWNER_NO"):
        raise Failure("%s is already done — write a NOTE instead" % task_id, EXIT_CONFLICT)
    if gate and entry.task.needs_owner and not entry.events_of("OWNER_OK"):
        raise Failure("%s needs owner confirmation first (`postbox owner-ok %s`)"
                      % (task_id, task_id), EXIT_NEEDS_OWNER)
    if status_state:
        # v1.1 order rule: STATUS is updated before the RESULT/BLOCKED lands.
        _write_status(cfg, state=status_state, current=task_id,
                      note="%s %s" % (kind.lower(), task_id))
    name = _event_name(entry, kind, agent, _files(box), unique=unique)
    text = core.render_event(kind, agent, core.fmt_ts(core.now(cfg.utc_offset_hours)),
                             body, instance=instance, **extra)
    payload = text.encode("utf-8")
    try:
        box.transport.create(name, payload)
    except ConflictError:
        # Same bytes means our own earlier attempt landed after a timeout —
        # idempotent. Different bytes means another writer owns that name.
        if box.transport.read(name) != payload:
            raise
    return name


def cmd_ack(args) -> int:
    cfg = args.cfg
    box = mailbox(cfg)
    try:
        entry = box.get(args.task)
    except KeyError as exc:
        raise Failure(exc.args[0] if exc.args else str(exc), EXIT_NOTFOUND) from None
    already = [e.agent for e in entry.events_of("ACK")]
    if cfg.agent in already:
        raise Failure("%s was already accepted by you (%s). Append a note instead."
                      % (entry.task.task_id, entry.events_of("ACK")[0].path), EXIT_CONFLICT)
    if already:
        raise Failure("%s was already accepted by %s — do not work on it twice."
                      % (entry.task.task_id, already[0]), EXIT_CONFLICT)
    body = args.note or "Received. Starting now."
    name = _write_event(cfg, entry.task.task_id, "ACK", body, cfg.agent, {}, gate=True,
                        unique=True)
    print(name)
    return EXIT_OK


def cmd_note(args) -> int:
    body = read_input(args.text, args.file, "note")
    name = _write_event(args.cfg, args.task, "NOTE", body, args.cfg.agent, {})
    print(name)
    return EXIT_OK


def _size_label(n: int) -> str:
    for unit, size in (("KB", 1024), ("MB", 1024 ** 2)):
        if n >= size:
            return "%.1f %s" % (n / size, unit)
    return "%d B" % n


def deliverable_manifest(paths: List[str], reason: str = "") -> str:
    """v1.1: a RESULT carries a manifest, because a summary is not a delivery."""
    if not paths:
        return "\n## Delivered\n\nNo files. %s\n" % (reason or "Reason not given.")
    rows = []
    for raw in paths:
        full = os.path.abspath(raw)
        if not os.path.isfile(full):
            raise Failure("artifact not found: %s" % raw, EXIT_USAGE)
        with open(full, "rb") as fh:
            data = fh.read()
        rows.append([os.path.basename(full), os.path.dirname(full),
                     _size_label(len(data)), core.sha256_bytes(data)])
    header = "| file | folder | size | sha256 |\n|---|---|---|---|"
    body = "\n".join("| %s | %s | %s | `%s` |" % tuple(row) for row in rows)
    return "\n## Delivered\n\n%s\n%s\n" % (header, body)


def cmd_result(args) -> int:
    cfg = args.cfg
    body = read_input(args.text, args.file, "result")
    if not args.artifact and not args.no_artifact:
        raise Failure(
            "attach what you delivered: --artifact <path> (repeatable), or "
            "--no-artifact \"why there is no file\"", EXIT_USAGE)
    if len(body.strip()) < 20:
        raise Failure("a RESULT must say what was done and where it lives "
                      "(at least 20 chars)", EXIT_USAGE)
    body += deliverable_manifest(args.artifact or [], args.no_artifact or "")
    name = _write_event(cfg, args.task, "RESULT", body, cfg.agent,
                        {"verified": "yes" if args.verified else "no"},
                        status_state="idle")
    print(name)
    return EXIT_OK


def cmd_blocked(args) -> int:
    cfg = args.cfg
    body = "%s\n\nAsked: %s" % (args.why.strip(), args.ask.strip() or "(unset)")
    name = _write_event(cfg, args.task, "BLOCKED", body, cfg.agent, {},
                        status_state="blocked")
    print(name)
    return EXIT_OK


def cmd_owner(args) -> int:
    kind = "OWNER_OK" if args.ok else "OWNER_NO"
    body = args.note or ("Approved to proceed." if args.ok else "Not approved. Stop.")
    name = _write_event(args.cfg, args.task, kind, body, args.cfg.agent, {}, unique=True)
    print(name)
    return EXIT_OK


def _write_status(cfg: Config, state: Optional[str] = None, current: Optional[str] = None,
                  last_seen: Optional[str] = None, note: Optional[str] = None,
                  heartbeat_only: bool = False) -> str:
    """Create or revise STATUS_<agent>.md (v1.1: heartbeat_at is its own field)."""
    name = "STATUS_%s%s" % (core.slug(cfg.agent), core.MD)
    now = core.fmt_ts(core.now(cfg.utc_offset_hours))
    transport = build(cfg)
    try:
        existing = transport.read(name).decode("utf-8", "replace")
    except FileNotFoundError:
        existing = ""
    if not existing.strip():
        text = core.render_status(cfg.agent, cfg.device, state or "idle",
                                  current or "none", last_seen or "none",
                                  note or "-", now)
    else:
        changes = {"protocol": core.PROTOCOL_LEVEL, "heartbeat_at": now}
        if not heartbeat_only:
            changes["updated_at"] = now
            if state:
                changes["state"] = state
            if current is not None:
                changes["current_task"] = current or "none"
            if last_seen is not None:
                changes["last_seen"] = last_seen or "none"
            if note is not None:
                changes["note"] = note or "-"
        text = core.revise_status(existing, **changes)
    transport.replace(name, text.encode("utf-8"))
    return name


def cmd_status(args) -> int:
    cfg = args.cfg
    if not args.state and not args.heartbeat:
        raise Failure("give a state (online|idle|working|blocked|offline) "
                      "or --heartbeat to refresh only the heartbeat", EXIT_USAGE)
    name = _write_status(cfg, state=args.state, current=args.current,
                         last_seen=args.last_seen, note=args.note,
                         heartbeat_only=bool(args.heartbeat and not args.state))
    print(name)
    return EXIT_OK


def cmd_watch(args) -> int:
    cfg = args.cfg
    paths = args.paths.split(",") if args.paths else cfg.watch_paths
    if args.state_dir:
        cfg.state_dir = args.state_dir
    code, output = watch_run(build(cfg), paths, cfg.state_path,
                             empty_is_error=not args.empty_ok,
                             self_agent=cfg.agent,
                             prefix=args.only_prefix or "")
    sys.stdout.write(output)
    return code


def cmd_lint(args) -> int:
    cfg = args.cfg
    box = mailbox(cfg)
    findings = lint(box, sla_hours=args.sla)
    if args.json:
        print(json.dumps([{"level": l, "code": c, "message": m} for l, c, m in findings],
                         ensure_ascii=False, indent=2))
    else:
        if not findings:
            print("clean — %d task(s), %d agent status file(s)"
                  % (len(box.entries), len(box.statuses())))
        for level, code, message in findings:
            print("%-5s %-22s %s" % (level.upper(), code, message))
    return EXIT_LINT if any(l == "error" for l, _c, _m in findings) else EXIT_OK


PROVIDERS = [
    {"preset": "git", "cn": "yes", "needs": "git + a repo (Gitee/GitHub/GitLab or a bare repo)",
     "what": "A private repository as the mailbox. Every write is one commit, so there is a free "
             "audit trail, and nothing touches Google. The most durable option.",
     "init": 'postbox init --transport git --clone https://gitee.com/YOU/inbox.git --agent alice\n'
             'postbox init --transport git --path /srv/inbox.git --agent bob'},
    {"preset": "local", "cn": "yes", "needs": "nothing (any folder your OS can see)",
     "what": "A folder that some sync tool replicates: Syncthing, Nutstore/坚果云 client, "
             "Dropbox, OneDrive, iCloud, a USB stick, a LAN share.",
     "init": 'postbox init --transport local --path "/path/to/shared/postbox" --agent alice'},
    {"preset": "webdav", "cn": "yes", "needs": "rclone + WebDAV url and app password",
     "what": "Nutstore (坚果云), Nextcloud, Alist, or any WebDAV server. No Google involved.",
     "init": 'rclone config create nutstore webdav url=https://dav.jianguoyun.com/dav/ user=YOU pass=APP_PASSWORD\n'
             'postbox init --transport rclone --remote nutstore:postbox --agent alice'},
    {"preset": "sftp", "cn": "yes", "needs": "rclone + ssh key",
     "what": "Your own VPS over SSH. Great if the agents are on machines you already own.",
     "init": 'rclone config create vps sftp host=1.2.3.4 user=ubuntu key_file=~/.ssh/id_ed25519\n'
             'postbox init --transport rclone --remote vps:postbox --agent alice'},
    {"preset": "s3", "cn": "depends", "needs": "rclone + endpoint/key",
     "what": "S3-compatible storage: MinIO, Cloudflare R2, Aliyun OSS (S3 gateway), Backblaze.",
     "init": 'rclone config create store s3 provider=Other endpoint=... access_key_id=... secret_access_key=...\n'
             'postbox init --transport rclone --remote store:postbox --agent alice'},
    {"preset": "gdrive", "cn": "no", "needs": "rclone + Google OAuth (needs access to Google)",
     "what": "Google Drive. Simplest if you already have it, unusable where Google is blocked.",
     "init": 'rclone config            # create a drive remote, then:\n'
             'postbox init --transport rclone --remote gdrive:team/postbox --agent alice'},
    {"preset": "onedrive", "cn": "no", "needs": "rclone + Microsoft OAuth",
     "what": "OneDrive / SharePoint.",
     "init": 'rclone config            # create a onedrive remote, then:\n'
             'postbox init --transport rclone --remote onedrive:postbox --agent alice'},
    {"preset": "dropbox", "cn": "no", "needs": "rclone + Dropbox OAuth",
     "what": "Dropbox.",
     "init": 'rclone config            # create a dropbox remote, then:\n'
             'postbox init --transport rclone --remote dropbox:postbox --agent alice'},
]

INSTRUCTIONS_EN = """# PostBox-M — operating rules for the agent

You are one agent in a shared mailbox. The mailbox is a folder; other agents
write to it too, and none of you can talk to the others directly.

## Every task addressed to you

1. `postbox inbox` — what is mine.
2. `postbox show <id>` — read the task and its history before acting.
3. `postbox ack <id>` — claim it. Exit 3 means someone else has it: stop, do not work on it.
4. Do the work. `postbox note <id> --text "..."` on long jobs.
5. `postbox result <id> --artifact <file> [--artifact ...] --text "what/where"`
   No file to deliver: `--no-artifact "<reason>"`. A sentence in chat is not a delivery.
6. `postbox status idle` when you stop working.

## Hard rules

- Never edit a task file, a RESULT, or another agent's file. Add a new file.
- `needs_owner_confirm: yes` means do not start. `postbox owner-ok <id>` is the
  only thing that unblocks it; exit code 5 means "not approved yet".
- Never write passwords, tokens, card numbers or ID numbers into the mailbox.
- Deliverables must be files with a size and a hash, listed in the RESULT.
- Poll with `postbox watch`: exit 0 = nothing changed (do nothing, say nothing),
  10 = something changed (read the diff, then `postbox inbox`), 11 = mailbox
  unreachable (report it; do not guess what changed).
- One task, one owner. If in doubt, `postbox show` before doing anything.

## Exit codes

0 ok | 2 usage | 3 conflict | 4 not found | 5 needs approval | 6 lint errors |
10 changed | 11 degraded / unreachable
"""

INSTRUCTIONS_ZH = """# PostBox-M — 给 Agent 的操作规则

你是共享邮箱里的一个 Agent。邮箱就是一个文件夹，别的 Agent 也在往里写，
你们之间没有直接的通信通道。

## 每个派给你的任务

1. `postbox inbox` — 哪些是我的。
2. `postbox show <id>` — 动手之前先读任务和它的历史。
3. `postbox ack <id>` — 认领。退出码 3 表示别人已经认领：停手，不要做。
4. 干活。长任务用 `postbox note <id> --text "..."` 记进度。
5. `postbox result <id> --artifact <文件> ... --text "做了什么/成品在哪"`
   没有文件就 `--no-artifact "理由"`。聊天里说一句"完成了"不算交付。
6. 收工时 `postbox status idle`。

## 硬规则

- 不许改任务文件、RESULT、别人的文件。要补充就新建文件。
- 任务写了 `needs_owner_confirm: yes` 就不许开工，只有 `postbox owner-ok <id>`
  能解锁；退出码 5 就是"还没批准"。
- 密码、token、卡号、身份证号一律不许写进邮箱。
- 交付物必须是文件，要带大小和哈希，写进 RESULT 的清单。
- 轮询用 `postbox watch`：退出码 0 = 没变化（什么都别做，也别说话），
  10 = 有变化（先看 diff，再 `postbox inbox`），11 = 邮箱不可达（如实报告，
  不要猜发生了什么）。
- 一个任务只有一个负责人。拿不准就先 `postbox show`。

## 退出码

0 正常 | 2 用法错 | 3 冲突 | 4 找不到 | 5 待批准 | 6 lint 有错 |
10 有变化 | 11 降级/不可达
"""


def cmd_providers(args) -> int:
    if args.json:
        print(json.dumps(PROVIDERS, ensure_ascii=False, indent=2))
        return EXIT_OK
    rows = [[p["preset"], p["cn"], p["needs"], p["what"]] for p in PROVIDERS]
    print(table(rows, ["PRESET", "IN CN", "NEEDS", "WHAT IT IS"]))
    print("")
    print("# ready-to-run (swap the path / remote / agent name)")
    for item in PROVIDERS:
        print("\n[%s]" % item["preset"])
        for line in item["init"].split("\n"):
            print("  " + line)
    print("\n# the 'local' preset needs no rclone and no Google: any folder your "
          "sync tool already replicates\n# point two checkouts at it with --path "
          "and you are done")
    return EXIT_OK


def cmd_instructions(args) -> int:
    text = INSTRUCTIONS_ZH if args.lang == "zh" else INSTRUCTIONS_EN
    if args.json:
        print(json.dumps({"language": args.lang, "format": "markdown", "text": text},
                         ensure_ascii=False, indent=2))
    else:
        sys.stdout.write(text)
    return EXIT_OK


def cmd_archive(args) -> int:
    """Move finished work out of the live queue into `_archive/<year-month>/`."""
    cfg = args.cfg
    box = mailbox(cfg)
    transport = box.transport
    cutoff = core.now(cfg.utc_offset_hours) - timedelta(days=max(args.days, 0))

    picks = []
    for entry in box.entries:
        if entry.state != "done":
            continue
        stamp = core.parse_ts(entry.updated) or core.parse_ts(
            entry.task.meta.get("created_at", ""))
        if stamp is None or stamp > cutoff:
            continue
        prefix = entry.task.path[:-len(core.MD)]
        names = [f.name.split("/")[-1] for f in box.files
                 if f.name.split("/")[-1] == entry.task.path
                 or f.name.split("/")[-1].startswith(prefix + "_")]
        picks.append((stamp, entry.task.task_id, sorted(names)))

    if not picks:
        print(i18n.tpl("nothing to archive (no finished task older than %d days)",
                       "没有可归档的（%d 天以前完成的才算）") % args.days)
        return EXIT_OK

    for stamp, task_id, names in picks:
        month = stamp.strftime("%Y-%m")
        if not args.apply:
            if i18n.is_zh():
                print("将移动 %s 的 %d 个文件 → _archive/%s/" % (task_id, len(names), month))
            else:
                print("would move %d file(s) of %s → _archive/%s/" % (len(names), task_id, month))
            continue
        for name in names:
            target = "_archive/%s/%s" % (month, name)
            try:
                payload = transport.read(name)
            except FileNotFoundError:
                continue
            if not transport.exists(target):
                transport.create(target, payload)
            else:
                current = transport.read(target)
                if current != payload:      # never overwrite archived evidence
                    continue
            transport.delete(name)

    if args.apply:
        total = sum(len(n) for _s, _t, n in picks)
        if i18n.is_zh():
            print("已归档 %d 个任务、%d 个文件" % (len(picks), total))
        else:
            print("archived %d task(s), %d file(s)" % (len(picks), total))
    else:
        print(i18n.tpl("dry run — add --apply to move them", "试运行 —— 加 --apply 才会真移动"))
    return EXIT_OK


def cmd_doctor(args) -> int:
    cfg = args.cfg
    problems = 0
    print("config   %s" % os.path.join(cfg.root, ".postbox", "config.json"))
    print("transport %s%s" % (cfg.transport, "  " + (cfg.remote or cfg.resolve(cfg.path))))
    try:
        t = build(cfg)
        files = t.list()
        print(i18n.tpl("reachable yes — %d object(s)", "可达 yes — %d 个文件") % len(files))
        probe = ".postbox-write-probe-%d.md" % os.getpid()
        try:
            t.create(probe, b"probe")
            if t.read(probe) != b"probe":
                raise TransportError("read-back mismatch")
            t.delete(probe)
            print(i18n.tpl("writable  yes — create, read, delete all work",
                       "可写      yes — 建/读/删都正常"))
        except (ConflictError, TransportError, FileNotFoundError, OSError) as exc:
            problems += 1
            print("writable  NO  — %s" % str(exc)[:200])
    except TransportError as exc:
        problems += 1
        print("reachable NO  — %s" % str(exc)[:300])
    print("state    %s" % cfg.state_path)
    try:
        box = mailbox(cfg)
        print("tasks    %d" % len(box.entries))
        print("agents   %s" % (", ".join(sorted(box.statuses())) or "(no STATUS files)"))
    except TransportError:
        problems += 1
    if cfg.agent in ("", "agent-a"):
        problems += 1
        print("agent    %s  ← set a real name: postbox init --agent <name>" % cfg.agent)
    return EXIT_OK if problems == 0 else 1


# --------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="postbox",
        description="A shared folder as the message bus between autonomous agents.")
    parser.add_argument("--version", action="version", version="postbox " + __version__)
    parser.add_argument("--root", default=".", help="checkout holding .postbox/ (default: .)")
    parser.add_argument("--agent", default="", help="override the agent name from config")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--lang", default="", choices=["", "en", "zh"],
                        help="human output language (default: config 'lang', then English)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="create .postbox/config.json and the mailbox")
    p.add_argument("--dir", default=None, help="checkout root (default: --root)")
    p.add_argument("--agent", default=argparse.SUPPRESS, help="this agent's name")
    p.add_argument("--transport", default="local", choices=["local", "rclone", "git"])
    p.add_argument("--path", default="shared", help="local folder (relative to root)")
    p.add_argument("--remote", default="", help="rclone remote folder, e.g. gdrive:agents/inbox")
    p.add_argument("--rclone-bin", default="", help="path to rclone (default: PATH)")
    p.add_argument("--rclone-config", default="", help="path to rclone.conf")
    p.add_argument("--clone", default="", help="git transport: clone this URL into --path")
    p.add_argument("--git-bin", default="", help="path to git (default: PATH)")
    p.add_argument("--git-branch", default="", help="git transport: branch (default: current)")
    p.add_argument("--device", default="")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("new", help="create a task")
    p.add_argument("--to", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--ask", default=None, help="what is wanted ('-' = stdin)")
    p.add_argument("--ask-file", default=None)
    p.add_argument("--background", default=None)
    p.add_argument("--done", default=None)
    p.add_argument("--accept", default=None)
    p.add_argument("--priority", default="normal", choices=["low", "normal", "high", "urgent"])
    p.add_argument("--needs-owner", action="store_true")
    p.add_argument("--urgent", action="store_true",
                   help="URGENT_ prefix: picked up by the 5-minute urgent lane")
    p.add_argument("--sender", default=None)
    p.set_defaults(func=cmd_new)

    p = sub.add_parser("dispatch", help="create many tasks from a JSON array")
    p.add_argument("file")
    p.set_defaults(func=cmd_dispatch)

    p = sub.add_parser("ls", help="list tasks")
    p.add_argument("--all", action="store_true")
    p.add_argument("--state", default="")
    p.add_argument("--to", default="")
    p.add_argument("--mine", default="")
    p.add_argument("--json", action="store_true", default=argparse.SUPPRESS,
                   help="machine-readable output")
    p.set_defaults(func=cmd_ls)

    p = sub.add_parser("show", help="show one task and its events")
    p.add_argument("task")
    p.add_argument("--json", action="store_true", default=argparse.SUPPRESS,
                   help="machine-readable output")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("inbox", help="what needs me")
    p.add_argument("--json", action="store_true", default=argparse.SUPPRESS,
                   help="machine-readable output")
    p.set_defaults(func=cmd_inbox)

    p = sub.add_parser("ack", help="accept a task (exclusive: first ACK wins)")
    p.add_argument("task")
    p.add_argument("--note", default=None)
    p.set_defaults(func=cmd_ack)

    p = sub.add_parser("note", help="append progress without changing state")
    p.add_argument("task")
    p.add_argument("--text", default=None)
    p.add_argument("--file", default=None)
    p.set_defaults(func=cmd_note)

    p = sub.add_parser("result", help="deliver the outcome")
    p.add_argument("task")
    p.add_argument("--text", default=None)
    p.add_argument("--file", default=None)
    p.add_argument("--artifact", action="append", default=[],
                   help="a file you delivered (repeatable); hashed into the manifest")
    p.add_argument("--no-artifact", default="", metavar="REASON",
                   help="why there is no file to deliver")
    p.add_argument("--verified", action="store_true", help="facts checked at the source")
    p.set_defaults(func=cmd_result)

    p = sub.add_parser("blocked", help="report a blocker")
    p.add_argument("task")
    p.add_argument("--why", required=True)
    p.add_argument("--ask", default="")
    p.set_defaults(func=cmd_blocked)

    p = sub.add_parser("owner-ok", help="record the human approval a task asked for")
    p.add_argument("task")
    p.add_argument("--note", default=None)
    p.set_defaults(func=cmd_owner, ok=True)

    p = sub.add_parser("owner-no", help="record that the human said no")
    p.add_argument("task")
    p.add_argument("--note", default=None)
    p.set_defaults(func=cmd_owner, ok=False)

    p = sub.add_parser("status", help="refresh my STATUS_<agent>.md")
    p.add_argument("state", nargs="?", default=None,
                   choices=["online", "idle", "working", "blocked", "offline"])
    p.add_argument("--heartbeat", action="store_true",
                   help="refresh heartbeat_at only (keeps state/note untouched)")
    p.add_argument("--current", default="")
    p.add_argument("--last-seen", default="")
    p.add_argument("--note", default="")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("watch", help="deterministic change check for pollers")
    p.add_argument("--paths", default="", help="comma separated, default from config")
    p.add_argument("--state-dir", default="")
    p.add_argument("--only-prefix", default="",
                   help="only consider names starting with this (e.g. URGENT_)")
    p.add_argument("--empty-ok", action="store_true", help="accept an empty listing")
    p.set_defaults(func=cmd_watch)

    p = sub.add_parser("lint", help="review the mailbox for broken hand-offs")
    p.add_argument("--sla", type=int, default=0)
    p.add_argument("--json", action="store_true", default=argparse.SUPPRESS,
                   help="machine-readable output")
    p.set_defaults(func=cmd_lint)

    p = sub.add_parser("doctor", help="is this checkout able to talk?")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("archive", help="move finished tasks older than N days out of the live queue")
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--apply", action="store_true",
                   help="actually move them (default: dry run)")
    p.set_defaults(func=cmd_archive)

    p = sub.add_parser("providers", help="storage backends that work, with the command for each")
    p.add_argument("--json", action="store_true", default=argparse.SUPPRESS,
                   help="machine-readable output")
    p.set_defaults(func=cmd_providers)

    p = sub.add_parser("instructions",
                       help="print the rules an AI agent must follow (paste into its prompt)")
    p.add_argument("--lang", default="en", choices=["en", "zh"])
    p.add_argument("--json", action="store_true", default=argparse.SUPPRESS,
                   help="machine-readable output")
    p.set_defaults(func=cmd_instructions)
    return parser


def _force_utf8() -> None:
    """Windows consoles default to a legacy code page; our output has arrows and Chinese.

    Without this, `postbox providers` dies with UnicodeEncodeError on any machine whose
    stdout is cp1252/cp437 — including the GitHub Actions runner and a plain cmd.exe.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def main(argv: Optional[List[str]] = None) -> int:
    _force_utf8()
    parser = build_parser()
    args = parser.parse_args(argv)
    i18n.set_lang(getattr(args, "lang", "") or os.environ.get("POSTBOX_LANG", ""))
    try:
        if args.command in ("init", "providers", "instructions"):
            # these three must work before a mailbox exists: they are how you pick one
            args.cfg = None
            return args.func(args)
        cfg = Config.load(args.root)
        cfg.agent = core.slug(args.agent or cfg.agent, fallback="agent-a")
        i18n.set_lang(getattr(args, "lang", "") or cfg.lang
                      or os.environ.get("POSTBOX_LANG", ""))
        if args.command == "lint" and not args.sla:
            args.sla = cfg.sla_hours
    except FileNotFoundError as exc:
        print("%s: %s" % (i18n.tpl("error", "错误"), i18n.tr(str(exc))), file=sys.stderr)
        return EXIT_USAGE
    args.cfg = cfg
    try:
        return args.func(args)
    except Failure as exc:
        print("%s: %s" % (i18n.tpl("error", "错误"), i18n.tr(str(exc))), file=sys.stderr)
        return exc.code
    except ConflictError as exc:
        print("%s: %s %s"
              % (i18n.tpl("conflict", "冲突"), i18n.tr(str(exc)),
                 i18n.tpl("(someone else got there first)", "（别人先到了）")),
              file=sys.stderr)
        return EXIT_CONFLICT
    except TransportError as exc:
        print("%s: %s" % (i18n.tpl("transport", "传输"), i18n.tr(str(exc))), file=sys.stderr)
        return 1
    except KeyError as exc:
        message = exc.args[0] if exc.args else str(exc)
        print("%s: %s" % (i18n.tpl("error", "错误"), i18n.tr(str(message))), file=sys.stderr)
        return EXIT_NOTFOUND


if __name__ == "__main__":
    raise SystemExit(main())
