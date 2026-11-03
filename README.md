# PostBox-M

**Turn the shared folder you already have into a task inbox between autonomous agents.**

[中文说明](README.zh-CN.md)

You run several agents on machines that cannot talk to each other: a laptop, a desktop, a cloud box. The one thing they already share is a folder — Google Drive, Dropbox, Syncthing, a network share. PostBox-M makes that folder a task queue with a durable hand-off record.

No server, no database, no broker, no per-agent API keys. Python standard library only; the network backend is `rclone`, so you reuse the OAuth you already did.

## What it actually fixes

1. **A task is discovered once and claimed once.** `ack` is exclusive; the second agent gets exit code 3 instead of doing the work twice.
2. **Records are never overwritten.** Task files are written once and never edited. ACKs, results and blockers are separate immutable files named after their author.
3. **Human approval cannot be bypassed.** A task with `needs_owner_confirm: yes` refuses `ack` (exit 5) until someone runs `owner-ok`.
4. **Polling costs nothing when nothing happens.** `postbox watch` prints byte-identical output until the folder changes, so a supervisor can diff stdout and skip the model entirely.
5. **A flaky drive doesn't become a page storm.** Rate limits, outages and crashes replay the last good baseline plus one constant marker line.

## Install

```bash
uv tool install postbox-m     # or: pip install postbox-m
```

Zero runtime dependencies. Backend is either `rclone` (Google Drive, OneDrive, S3, WebDAV…) or a plain local folder that some sync tool replicates.

## Five-minute tour

```bash
# machine A
postbox init --transport rclone --remote gdrive:team/inbox --agent alice
postbox new --to bob --title "weekly report" \
  --ask "Five bullets, each with a primary source and a date" \
  --accept "Five bullets, no filler, links open"

# machine B
postbox init --transport rclone --remote gdrive:team/inbox --agent bob
postbox inbox
postbox ack 20261102-1806-alice-to-bob-01 --note "on it, 6pm"
postbox result 20261102-1806-alice-to-bob-01 --artifact weekly.md --verified

# machine A
postbox inbox     # replies on tasks you sent →
postbox show 20261102-1806-alice-to-bob-01
```

Offline / no drive at all:

```bash
postbox init --transport local --path /path/to/shared-folder --agent alice
```

## Commands

| command | what it does |
|---|---|
| `init` | create `.postbox/config.json` and the mailbox |
| `new` | create a task (`--needs-owner` gates it behind human approval) |
| `dispatch tasks.json` | create a batch from JSON |
| `inbox` | tasks for me, tasks waiting for approval, new replies on what I sent |
| `ls` / `show` | list / one task with its full event history |
| `ack` | claim (3 = already claimed, 5 = needs approval) |
| `note` | progress, no state change |
| `result` | deliver: `--artifact <file>` (repeatable) builds the manifest, or `--no-artifact "<reason>"` |
| `blocked` | report a blocker and who you are asking |
| `owner-ok` / `owner-no` | record the human decision |
| `status` | refresh `STATUS_<agent>.md` heartbeat |
| `watch` | deterministic change check: 0 unchanged, 10 changed, 11 degraded |
| `lint` | duplicate ids, orphan events, double results, empty deliveries, zombie heartbeats, leaked secrets, sync conflict copies |
| `doctor` | can this checkout talk? reachable + **writable**, proven with a create/read/delete probe |
| `providers` | every backend that works, marked for mainland China, with a runnable command |
| `instructions` | print the rules an AI agent must follow (`--lang zh`) |

Exit codes carry meaning: `0` ok, `2` usage, `3` conflict, `4` not found, `5` needs approval, `6` lint errors, `10` changed, `11` degraded.

## No Google Drive, no VPN

The mailbox is just a folder. Anything that replicates a folder between two
machines is a valid backend, and only three of the presets involve Google at all.

```
$ postbox providers
PRESET    IN CN    NEEDS                      WHAT IT IS
local     yes      nothing                    a folder your existing sync tool replicates
webdav    yes      rclone + url/app password  Nutstore (坚果云), Nextcloud, Alist
sftp      yes      rclone + ssh key            a VPS you already own
s3        depends  rclone + endpoint/key       MinIO, R2, Aliyun OSS via its S3 gateway
gdrive    no       rclone + Google OAuth       Google Drive
onedrive  no       rclone + Microsoft OAuth    OneDrive / SharePoint
```

`local` is the one to try first: no rclone, no OAuth, no account, no network.
Point two checkouts at the same folder and you have a working mailbox — which is
exactly how the test suite runs.

Two honest caveats for desktop sync clients:

- a file exists for the other side only once the client has synced it, so the
  poll interval has to be longer than your sync latency;
- when two edits collide, the client writes `foo (1).md` next to `foo.md`. The
  original keeps its name and PostBox ignores the copy; `lint` reports it as
  `sync_conflict_copy`, but somebody has to actually look at it.

## Telling the AI what to do

A mailbox only works if the agents share the same rules. `postbox instructions`
prints that rulebook — acknowledge before working, never edit another agent's
file, exit code 10 means "something changed", a RESULT without a manifest is not
a delivery:

```
postbox instructions > AGENTS.md     # or: postbox instructions --lang zh
```

Paste it into the system prompt, `AGENTS.md`, `CLAUDE.md`, a project skill, or
whatever your agent reads at startup. `examples/AGENTS.md` ships the same text.

## On disk

```
2026-11-02_TASK-20261102-1806-alice-to-bob-01_alice-to-bob_weekly-report.md
                                    ..._ACK_bob.md
                                    ..._RESULT_bob.md
```

```markdown
---
id: 20261102-1806-alice-to-bob-01
created_at: 2026-11-02 18:06:45 +0800
from: alice
to: bob
priority: normal
state: new
needs_owner_confirm: no
---

# weekly report
```

Long file names are the wire format. The upside is that a human can read, fix and audit the queue from a phone; the downside is that file names are long. I picked repairable.

## Design decisions worth knowing

**State is derived, not stored.** `state:` is written once at creation. Everything after that is inferred from immutable event files: an ACK means `ack`, a RESULT means `done`, a BLOCKED means `blocked`. There is no "update the status line" operation, so there is no last-writer-wins race on a status line.

**Claiming is not a lock.** Google Drive has no atomic create — `rclone copyto --immutable` silently overwrites on Drive (returncode 0, measured), so every "reserve this name" trick is a fake mutex. PostBox-M instead gives each task exactly one owner, names every event after its author, and verifies writes by reading them back. Mutual exclusion comes from the one-owner rule, not from an API promise.

**Pollers must be byte-stable.** `postbox watch` prints exactly the same bytes until something changes. On failure it replays the last baseline plus a constant `STATUS|DEGRADED|…` line — no timestamps, or every tick would look new and wake the model forever. Two consecutive failures are required before that line appears, and it disappears on recovery: one wake-up per outage.

**Idempotency lives above the transport.** `create` treats an existing name as a conflict and does not guess. Whether a conflict is "my own retry" is decided by the application using an `instance: <pid>-<host>` field in the front matter. Pushing idempotency down into `create` makes every concurrent claim "succeed".

**A fingerprint without a hash is a guess.** Name + size + mtime misses a file edited in place to the same length within the same second — and it misses it silently, which is the worst kind. The watch line carries an md5 (`rclone` gets it from Drive's own `md5Checksum`, no extra request). When the backend cannot supply a hash the line ends in `-` and one `HASH|missing|<n>` line appears, because a degraded fingerprint should look degraded. Same logic applies to delivery: `result` refuses to be a paragraph. `--artifact` writes file, folder, size and sha256 into the RESULT; `--no-artifact "<reason>"` is the only way out. A sentence in a chat is not a deliverable.

## Limits

- **Not real-time.** Latency equals your sync layer (seconds on Google Drive). Fine for tasks, useless for tight coordination.
- **No authority.** A file saying "approved" is not an approval; `needs_owner_confirm` makes the gate impossible to skip, not attributable.
- **No transactions.** Read-back verification and single ownership keep the odds low; two deliberate writers racing inside the same second can still both think they won.
- **Do not store secrets.** `lint` recognises common key formats and fails loudly, but it is a smoke detector, not a vault.

## Compatibility

The naming follows a convention that has been running in production for months (`YYYY-MM-DD_TASK-<id>_<from>to<to>_<title>.md`, `_ACK_<agent>.md`, `STATUS_<agent>.md`), so an existing shared folder can be adopted as-is. Unrelated files and old-format notes are ignored, never modified.

## Docs

- [`docs/protocol.md`](docs/protocol.md) — the normative spec
- [`docs/design-notes.md`](docs/design-notes.md) — why it is built this way, including the measurements

## About

Built and maintained by **闷闷AI说** — a channel about AI news and hands-on tests. The tool exists because relaying tasks by hand between agents on different machines does not scale; a shared folder plus immutable events turned out to hold on any storage, so it became a project.

- YouTube: <https://www.youtube.com/@menmenAI>
- Bilibili: <https://space.bilibili.com/34234499>

MIT licensed.
