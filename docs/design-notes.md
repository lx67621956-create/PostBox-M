# Design notes

Why the thing looks like this, including the measurements that forced each
decision. If you are about to "simplify" one of these parts, read the section
that covers it first.

## The premise

N agents, N machines, one folder they can all read and write, no network path
between them, no shared credential beyond that folder. Typical setup: laptop,
desktop, a cloud box, and a human who is tired of copy-pasting task descriptions.

The tool has to work when the folder is Google Drive (no atomic ops, rate
limits, a shared OAuth client), when it is a Syncthing folder (eventual
consistency), and when it is a USB stick (no clock guarantee).

## Rejected alternatives

| option | why not |
|---|---|
| a queue service (Redis, SQS, RabbitMQ) | needs a server, a key, and a network path that the whole premise says doesn't exist |
| SQLite on the shared folder | locked or corrupted by cloud sync; one sync conflict and the queue is gone |
| a git repo as the mailbox | merge conflicts are a human problem, and every agent needs git identity + a remote |
| one shared JSON file | lost updates; two writers, one survives, no audit trail |
| chat/email bridge | works, but the queue state lives in a mailbox you don't control |

A folder of immutable Markdown files has one big advantage over all of them: when
something goes wrong at 2am, a human can open it on a phone and fix it by hand.

## Problem 1 — nothing on a cloud drive is atomic

The obvious design is "create a claim file, first writer wins". That assumes
`create` fails when the name exists. On Google Drive it does not:

```
$ rclone copyto --immutable new.txt gdrive:test/t.md   # t.md already exists, different content
$ echo $?
0
$ rclone cat gdrive:test/t.md
second content longer                                  # silently overwritten
```

So `--immutable` is not a mutex, and neither is anything else rclone exposes.
Google Drive's API allows duplicate names too, so "create with a unique name and
trust the counter" doesn't work either.

What actually holds:

1. **One owner per task.** No two agents are ever asked to arbitrate one file.
2. **Every file has exactly one author.** Events are named after their author and
   are never rewritten.
3. **Verify by reading back.** `create` lists first (refuse early), writes, waits
   a settle window, then compares the bytes that are really there.

The residual race is "two writers within one round trip". Every writer detects it
afterwards, and the losing side reports a conflict instead of silently proceeding.
Calling that a lock would be a lie; it is a conflict *detector*.

## Problem 2 — any mutable state file loses writes

An early version kept `state: working` in the task file and updated it. Two
agents touching one task, or one agent rewriting while another read, produced
states that contradicted the event history. Worse, the wrong value looked
authoritative because it was at the top of the file.

The fix is boring and total: **the task file is written once and never edited**.
Every later fact is a new file. State becomes a pure function of the folder
contents, so any reader — this CLI, another agent, a human — derives the same
answer. There is no "last writer wins" for state because there is no writer.

The cost is more files. A task with an ACK and a RESULT is three files. That is
acceptable: it is also the audit trail.

## Problem 3 — polling burns the context window

An agent that checks the mailbox every five minutes and reads the whole folder
burns a model call on "nothing new" twelve times an hour. The supervisor pattern
that fixes this compares the poller's **stdout** with the previous tick and
skips the model when they are identical. That only works if identical folders
produce identical bytes, which rules out timestamps, random ordering, locale
sorting and "scanned 42 files in 0.8s" banners.

Three ways to get it wrong, all observed:

1. **Print the error.** `ERROR: token expired` replaces the baseline; on recovery
   every file looks new and the operator gets a flood. Also: the error string
   itself may contain a timestamp, so it differs every tick.
2. **Silently replay the cache on failure.** Looks clean; a folder that has been
   offline for a week is indistinguishable from a healthy one, and nobody is told.
3. **Replay the cache, then append one constant marker after N failures.**
   Chosen. A single failed tick prints the baseline unchanged (no wake-up); two
   in a row print `STATUS|DEGRADED|transport_unreachable` (one wake-up); recovery
   removes the line (one more wake-up). The marker must not contain a timestamp,
   otherwise "one wake-up" becomes "one per tick".

Related: an empty listing is treated as a failure whenever a baseline exists. A
revoked token returns `[]` with exit code 0, and accepting that would wipe the
baseline and make the next real listing look like a hundred new files.

## Problem 4 — Drive 404s a file it just accepted

Measured while verifying writes: right after `rclone copyto` reported success,
`rclone cat` returned exit code 3 (not found). Repeating the same read ~0.7s
later returned the full content. Without a retry, the tool reports a conflict on
a write that succeeded — the worst possible failure mode, because the caller then
retries and creates a duplicate.

So verification polls up to four times with a short sleep before concluding
anything. Conversely, exit codes 3 and 4 mean "not there" and must **not** be
retried: the default retry ladder (0/5/15s) turns every "does this file exist?"
into a 20-second wait. That one line (`if rc in (3, 4): raise NotFound`) took the
whole test suite from 61s to 9s.

Cost note on listings: on a real shared drive with ~100 files, a full recursive
listing took 22–87s and regularly tripped the rate limiter, while listing a single
45-file folder took 2.6s. `watch` therefore lists only the configured paths, and
reads come from a local mirror refreshed with one `rclone sync` per command.

## Problem 5 — idempotency versus exclusivity

The first `create` implementation accepted "same bytes already present" as
success. That is convenient for retries and catastrophic for claiming: six
processes writing an identical ACK payload in the same second all got exit code
0, and three of them believed they owned the task. Test output was literally
`[0, 0, 0, 3, 3, 3]`.

Rules that survived:

- `create` reports a conflict for any existing name, identical bytes or not.
- Retry tolerance lives in the command layer, and only when the existing bytes
  match exactly — which is safe only because every event carries
  `instance: <pid>-<host>` plus a second-resolution timestamp. Two processes on
  one host cannot share a pid; two hosts cannot share a hostname.
- Sequential repeat actions (`RESULT2`, `ACK2`) are explicit, not implicit.

## Problem 6 — `_` cannot be a value character

`OWNER_OK` is a kind with an underscore in it, while `_` is the field separator in
`<task>_<KIND>_<agent>.md`. Parsing by `split("_")` reads `OWNER` as the kind and
`alice` as the agent, so approvals were silently downgraded to `NOTE` and the
owner gate never opened. Parsing now strips the trailing `_<agent>` and matches
the longest known kind at the end of the remaining label; handles are slugged so
they can never contain `_`.

The lesson generalises: if the file name is the parse format, fix the alphabet
before writing the parser.

## Problem 7 — two checkouts on one machine

Two agents on the same laptop shared one cache directory keyed by the remote
name, so they shared the mirror and the `watch` baseline. Each one's writes
looked like the other's changes, and both pollers flapped. The state directory
now includes the agent name: `~/.cache/postbox/watch-<remote>-<agent>`.

## Known unsolved

- **Atomic claim on object storage.** Not possible without a real lock service.
  Mitigated by one-owner-per-task; not fixed.
- **Clock skew.** Ordering uses file mtimes from the backend, which are the
  backend's clock. A badly skewed writer can reorder events. Practically fine on
  one Google account; do not mix machines whose clocks are hours apart.
- **Timezones.** Every timestamp written by the tool carries an explicit offset;
  parsing without one assumes `utc_offset_hours` from the config.
- **Large mailboxes.** Everything is listed on every command. At thousands of
  files you want partitioning by month — not built, because a real deployment
  plateaus in the low hundreds.

## Problem 8 — a fingerprint without a hash is a guess

The first watch implementation compared `name|size|mtime`. That misses an edit
made in place when the new bytes are the same length and land inside the same
mtime tick — which is exactly what happens when a task file is rewritten with a
one-word change, or when a sync tool preserves mtimes.

The line now carries an md5. On Google Drive that costs nothing extra: `rclone
lsjson --hash` returns `Hashes.md5` from the metadata the listing already
fetched. For local folders we read the file; mailboxes are small Markdown files,
and `watch` reads each one once per tick.

Two rules make the degraded case honest rather than invisible:

- a missing hash renders as `-`, and one `HASH|missing|<n>` line is added to the
  output, so the fingerprint is visibly weaker;
- a backend that cannot hash at all still works — the fingerprint just stops
  catching same-size edits, and the operator can see that in the output.

The same principle, applied to deliverables, is why `result` requires a manifest.
"Completed" in a chat window has no size and no hash, so there is no way to tell
it from a task that was never done.
