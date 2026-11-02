"""Command line interface. `postbox --help` for the whole surface."""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import unicodedata
from typing import List, Optional

from . import __version__, core
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
    mirror = "" if cfg.transport == "local" else os.path.join(cfg.state_path, "mirror")
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
                 rclone_config=getattr(args, "rclone_config", ""))
    if args.transport == "rclone" and not args.remote:
        raise Failure("--transport rclone needs --remote, e.g. --remote gdrive:agents/inbox",
                      EXIT_USAGE)
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
    print("initialised %s" % cfg_path)
    print("mailbox   %s" % (cfg.remote or cfg.resolve(cfg.path)))
    print("agent     %s" % cfg.agent)
    print("next      postbox new --to <peer> --title \"...\" --ask \"...\"")
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
        name = core.task_filename(task_id, sender, args.to, body_title, when)
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
        raise Failure(str(exc), EXIT_NOTFOUND) from None
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
        print("nothing for %s" % me)
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


def _event_name(entry: Entry, kind: str, agent: str, existing: List[str]) -> str:
    base = core.event_filename(entry.task.path, kind, agent)
    if base not in existing:
        return base
    for n in range(2, 100):
        candidate = core.event_filename(entry.task.path, kind, agent, n)
        if candidate not in existing:
            return candidate
    raise Failure("too many %s files for %s" % (kind, entry.task.task_id), EXIT_CONFLICT)


def _files(box: Mailbox) -> List[str]:
    return [f.name.split("/")[-1] for f in box.files]


def _write_event(cfg: Config, task_id: str, kind: str, body: str, agent: str,
                 extra: dict, gate: bool = False) -> str:
    instance = "%d-%s" % (os.getpid(), socket.gethostname().split(".")[0][:24])
    box = mailbox(cfg)
    try:
        entry = box.get(task_id)
    except KeyError as exc:
        raise Failure(str(exc), EXIT_NOTFOUND) from None
    if entry.state == "done" and kind not in ("NOTE", "OWNER_OK", "OWNER_NO"):
        raise Failure("%s is already done — write a NOTE instead" % task_id, EXIT_CONFLICT)
    if gate and entry.task.needs_owner and not entry.events_of("OWNER_OK"):
        raise Failure("%s needs owner confirmation first (`postbox owner-ok %s`)"
                      % (task_id, task_id), EXIT_NEEDS_OWNER)
    name = _event_name(entry, kind, agent, _files(box))
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
        raise Failure(str(exc), EXIT_NOTFOUND) from None
    already = [e.agent for e in entry.events_of("ACK")]
    if cfg.agent in already:
        raise Failure("%s was already accepted by you (%s). Append a note instead."
                      % (entry.task.task_id, entry.events_of("ACK")[0].path), EXIT_CONFLICT)
    if already:
        raise Failure("%s was already accepted by %s — do not work on it twice."
                      % (entry.task.task_id, already[0]), EXIT_CONFLICT)
    body = args.note or "Received. Starting now."
    name = _write_event(cfg, entry.task.task_id, "ACK", body, cfg.agent, {}, gate=True)
    print(name)
    return EXIT_OK


def cmd_note(args) -> int:
    body = read_input(args.text, args.file, "note")
    name = _write_event(args.cfg, args.task, "NOTE", body, args.cfg.agent, {})
    print(name)
    return EXIT_OK


def cmd_result(args) -> int:
    cfg = args.cfg
    body = read_input(args.text, args.file, "result")
    if len(body.strip()) < 20:
        raise Failure("a RESULT must say what was done and where it lives "
                      "(at least 20 chars)", EXIT_USAGE)
    name = _write_event(cfg, args.task, "RESULT", body, cfg.agent,
                        {"verified": "yes" if args.verified else "no"})
    print(name)
    return EXIT_OK


def cmd_blocked(args) -> int:
    cfg = args.cfg
    body = "%s\n\nAsked: %s" % (args.why.strip(), args.ask.strip() or "(unset)")
    name = _write_event(cfg, args.task, "BLOCKED", body, cfg.agent, {})
    print(name)
    return EXIT_OK


def cmd_owner(args) -> int:
    kind = "OWNER_OK" if args.ok else "OWNER_NO"
    body = args.note or ("Approved to proceed." if args.ok else "Not approved. Stop.")
    name = _write_event(args.cfg, args.task, kind, body, args.cfg.agent, {})
    print(name)
    return EXIT_OK


def cmd_status(args) -> int:
    cfg = args.cfg
    text = core.render_status(cfg.agent, cfg.device, args.state, args.current or "none",
                              args.last_seen or "none", args.note or "-",
                              core.fmt_ts(core.now(cfg.utc_offset_hours)))
    name = "STATUS_%s%s" % (core.slug(cfg.agent), core.MD)
    build(cfg).replace(name, text.encode("utf-8"))
    print(name)
    return EXIT_OK


def cmd_watch(args) -> int:
    cfg = args.cfg
    paths = args.paths.split(",") if args.paths else cfg.watch_paths
    if args.state_dir:
        cfg.state_dir = args.state_dir
    code, output = watch_run(build(cfg), paths, cfg.state_path,
                             empty_is_error=not args.empty_ok)
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


def cmd_doctor(args) -> int:
    cfg = args.cfg
    problems = 0
    print("config   %s" % os.path.join(cfg.root, ".postbox", "config.json"))
    print("transport %s%s" % (cfg.transport, "  " + (cfg.remote or cfg.resolve(cfg.path))))
    try:
        files = build(cfg).list()
        print("reachable yes — %d object(s)" % len(files))
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
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="create .postbox/config.json and the mailbox")
    p.add_argument("--dir", default=None, help="checkout root (default: --root)")
    p.add_argument("--agent", default=argparse.SUPPRESS, help="this agent's name")
    p.add_argument("--transport", default="local", choices=["local", "rclone"])
    p.add_argument("--path", default="shared", help="local folder (relative to root)")
    p.add_argument("--remote", default="", help="rclone remote folder, e.g. gdrive:agents/inbox")
    p.add_argument("--rclone-bin", default="", help="path to rclone (default: PATH)")
    p.add_argument("--rclone-config", default="", help="path to rclone.conf")
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
    p.set_defaults(func=cmd_ls)

    p = sub.add_parser("show", help="show one task and its events")
    p.add_argument("task")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("inbox", help="what needs me")
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
    p.add_argument("state", choices=["online", "idle", "working", "blocked", "offline"])
    p.add_argument("--current", default="")
    p.add_argument("--last-seen", default="")
    p.add_argument("--note", default="")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("watch", help="deterministic change check for pollers")
    p.add_argument("--paths", default="", help="comma separated, default from config")
    p.add_argument("--state-dir", default="")
    p.add_argument("--empty-ok", action="store_true", help="accept an empty listing")
    p.set_defaults(func=cmd_watch)

    p = sub.add_parser("lint", help="review the mailbox for broken hand-offs")
    p.add_argument("--sla", type=int, default=0)
    p.set_defaults(func=cmd_lint)

    p = sub.add_parser("doctor", help="is this checkout able to talk?")
    p.set_defaults(func=cmd_doctor)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            args.cfg = None
            return args.func(args)
        cfg = Config.load(args.root)
        cfg.agent = core.slug(args.agent or cfg.agent, fallback="agent-a")
        if args.command == "lint" and not args.sla:
            args.sla = cfg.sla_hours
    except FileNotFoundError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return EXIT_USAGE
    args.cfg = cfg
    try:
        return args.func(args)
    except Failure as exc:
        print("error: %s" % exc, file=sys.stderr)
        return exc.code
    except ConflictError as exc:
        print("conflict: %s (someone else got there first)" % exc, file=sys.stderr)
        return EXIT_CONFLICT
    except TransportError as exc:
        print("transport: %s" % exc, file=sys.stderr)
        return 1
    except KeyError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return EXIT_NOTFOUND


if __name__ == "__main__":
    raise SystemExit(main())
