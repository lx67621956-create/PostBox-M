# PostBox-M wire protocol (v1)

This is the normative part. If a second implementation disagrees with this file,
this file wins. Everything here is plain UTF-8 Markdown in **one flat folder**.

## 1. Storage requirements

A backend must provide four operations:

| operation | semantics |
|---|---|
| `list` | names + size + mtime for the folder (not recursive by default) |
| `read` | full bytes of one object |
| `create(name, bytes)` | must not silently leave different bytes under that name |
| `replace(name, bytes)` | overwrite a file the caller owns (only `STATUS_<agent>.md`) |

No transaction, rename or delete primitive is required. `create` is *not*
required to be atomic — see §8.

A flat folder is assumed. Sub-folders are not part of the format.

## 2. Names

Handles (`agent`, `id` fragments, titles) go through `slug()`:
CJK and `A-Za-z0-9` are kept, everything else becomes `-`, **`_` never appears in
a handle** because it is the field separator. Max 48 chars.

### Task file

```
YYYY-MM-DD_TASK-<id>_<from>-to-<to>_<title>.md
```

- `<id>` = `YYYYMMDD-HHMM-<from>-to-<to>-<NN>`
- `<from>` / `<to>` are slugged agent handles
- `<title>` is a slugged short title

Example:

```
2026-11-02_TASK-20261102-1806-alice-to-bob-01_alice-to-bob_weekly-report.md
```

### Event file

`<task file name without .md>_<KIND><n>_<agent>.md`

Known kinds: `ACK`, `NOTE`, `RESULT`, `BLOCKED`, `QUESTION`, `OWNER_OK`,
`OWNER_NO`. `<n>` is the repeat counter (`ACK2`, `RESULT2`, …) and is omitted
for the first one. Any other label (e.g. a hand-written `_补充_alice.md`) is read
as `NOTE` so humans can scribble in the folder without breaking anything.

A file is an **event** if its name starts with an existing task's base name plus
`_`. Everything else is not a task and not an event — it is ignored.

### Status file

`STATUS_<agent>.md`, one per agent, rewritten only by its owner.

## 3. Task front matter

```yaml
---
id: 20261102-1806-alice-to-bob-01
created_at: 2026-11-02 18:06:45 +0800
from: alice
to: bob
priority: normal            # low | normal | high | urgent
state: new                  # written once, never updated
needs_owner_confirm: no     # yes -> see §6
---
```

Only flat `key: value` lines are defined. Parsers must tolerate CRLF, a BOM,
quoted values, and an extra `---`-less body. Any unknown key is preserved.

The body is free Markdown. The generator emits five sections: what is wanted,
background, already done, acceptance criteria, red lines.

## 4. Event front matter

```yaml
---
kind: ACK
agent: bob
at: 2026-11-02 18:07:32 +0800
instance: 11528-GothicPC     # <pid>-<host>, used for idempotency (§8)
---
```

`RESULT` adds `verified: yes|no` — whether the facts were checked at the source.

## 5. State derivation

State is a pure function of the task file plus its events, ordered by
`(mtime, file name)`:

```
state = new
for event in order:
    ACK       -> ack
    NOTE      -> working   (only if already ack/working)
    BLOCKED   -> blocked
    QUESTION  -> question
    RESULT    -> done      (terminal)
    OWNER_NO  -> rejected
    OWNER_OK  -> ack       (only if currently waiting_owner)
```

Then the owner gate (§6) may rewrite the result to `waiting_owner`.

Two implementations reading the same folder must produce the same state. No
state is ever written back to the task file.

## 6. Owner gate

If `needs_owner_confirm: yes` and no `OWNER_OK` event exists, the derived state is
`waiting_owner` and:

- `ack` must fail with exit code `5`
- `inbox` must list the task under "waiting for owner approval"
- `lint` must report `acked_without_owner` if an ACK exists anyway

`owner-ok` / `owner-no` are ordinary events; anyone with write access can create
them. This gate protects against *forgetting*, not against a hostile agent.

## 7. Delivery rules

- `result` requires ≥ 20 characters of body. "done" is not a delivery.
- A RESULT may be followed by RESULT2 (a revision). Two different agents
  submitting RESULT for the same task is a lint **error** (`double_result`).
- Nothing may be written into an existing event file. Repeats get `<n>`.

## 8. Concurrency and idempotency

**Rule: one task, one owner.** The protocol never asks two agents to arbitrate
the same file. Fan-out to N agents means N tasks.

`create` is "create if absent, best effort":

1. List the folder; if the name exists → `ConflictError` without writing.
2. Write the bytes.
3. Read the bytes back (with a short settle window) and compare.
4. Equal → success; different → `ConflictError`; unreadable → `TransportError`.

Because step 1 and step 2 are not atomic, a deliberate same-second race can
still produce two writers. Every writer then detects it in step 3 and exactly
one observes its own bytes. Do not build a mutex on top of this.

**Retry idempotency** is decided one level up: on `ConflictError`, read the file;
if the bytes are identical *including* `instance:`, this was our own earlier
attempt that landed after a timeout → treat as success. Different bytes →
a real conflict.

## 9. `status` file

```
agent: bob
device: desktop
updated_at: 2026-11-02 18:07:32 +0800
state: online|idle|working|blocked|offline
current_task: <id>|none
last_seen: <id or file>|none
note: <one line>
```

Seven lines. `lint` flags a status older than `sla_hours` (default 48h) and calls
`state: online|idle` with no refresh for 24h a **zombie**.

## 10. `watch` output contract

Purpose: a supervisor must be able to decide "nothing happened" **without
running a model**, byte for byte.

```
# postbox watch
<name>|<size>|<mtime>
...
FP|<16 hex chars>
```

- Lines are sorted; no timestamps are generated by the tool itself; nothing
  random; nothing locale-dependent. Same folder → same bytes.
- Exit `0` = unchanged, `10` = changed (or first run, no baseline yet),
  `11` = degraded.
- On change, three extra lines are appended:
  `CHANGED|+<n>|-<m>` followed by `+ ` / `- ` lines for added / removed entries.
  The next unchanged tick drops them (one extra wake-up per change; a
  supervisor that wants zero should key on the exit code only).
- On transport failure: replay the last baseline **and** append
  `STATUS|DEGRADED|transport_unreachable` — but only after `DEGRADED_AFTER = 2`
  consecutive failures. Before that, print the baseline unchanged so a blip
  causes no wake-up. The marker contains no timestamp, so an outage wakes the
  supervisor exactly once and recovery wakes it once more.
- An empty listing while a baseline exists is treated as a failure, never as
  "everything was deleted" — otherwise a broken token would wipe the baseline.
- With no baseline at all, print `STATUS|DEGRADED|no_baseline` and the raw
  reason: the only case where an error string is the right answer.

## 11. Lint rules

| code | level | meaning |
|---|---|---|
| `duplicate_id` | error | same task id in two files |
| `orphan_event` | warn | looks like an event, matches no task |
| `double_result` | error | two agents delivered the same task |
| `repeated_result` | warn | same agent delivered twice (revision?) |
| `acked_without_owner` | error | ACK on a task that needed approval |
| `empty_result` | warn | RESULT body < 20 chars |
| `stale_task` | warn | acked/working longer than `sla_hours` |
| `blocked_no_question` | warn | blocked without asking anyone |
| `no_status` | warn | no `STATUS_*` file at all |
| `stale_status` | warn | status not refreshed within SLA |
| `zombie_status` | error | claims online/idle but stale > 24h |
| `secret` | error | PEM key, AWS/GitHub/OpenAI/Google/Slack token, CN ID, `password: …` |

## 12. Interop

- A human may edit any file, but editing a *task* breaks the "written once"
  invariant; prefer adding a `NOTE` file.
- Legacy or foreign files are ignored, never rewritten.
- Other tools may implement this spec as long as §5 produces identical states.
