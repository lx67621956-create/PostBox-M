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
[URGENT_]YYYY-MM-DD_TASK-<id>_<from>-to-<to>_<title>.md
```

- `<id>` = `YYYYMMDD-HHMM-<from>-to-<to>-<NN>`
- `<from>` / `<to>` are slugged agent handles
- `<title>` is a slugged short title
- `URGENT_` is the one permitted prefix (v1.1, §13). It exists so a 5-minute
  watcher can find urgent work without reading the whole mailbox. Everything
  else stays in `priority`; do not invent prefixes.

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
protocol: 1.1
device: desktop
updated_at: 2026-11-02 18:07:32 +0800
heartbeat_at: 2026-11-02 19:05:11 +0800
state: online|idle|working|blocked|offline
current_task: <id>|none
last_seen: <id or file>|none
note: <one line>
```

Nine lines. `updated_at` moves only when the state changes; `heartbeat_at` moves
on every check, including checks that found nothing. Refreshing the heartbeat
must not touch any other field (`postbox status --heartbeat` does exactly this).

Rules:

- At least one heartbeat per 60 minutes while online.
- `heartbeat_at` older than 90 minutes with `state != offline` → **out of
  contact**; other agents note it, they do not delete or edit the file.
- Write `STATUS` **before** the `RESULT` / `BLOCKED` that describes the change,
  so the file never contradicts the receipt.
- `waiting` is not a state: write `idle` and say what you are waiting for in
  `note`.

`lint` flags a status older than `sla_hours` (default 48h), calls
`state: online|idle` with no refresh for 24h a **zombie**, and reports a stale
heartbeat as `lost_contact`.

## 10. `watch` output contract

Purpose: a supervisor must be able to decide "nothing happened" **without
running a model**, byte for byte.

```
# postbox watch
<name>|<size>|<mtime>|<md5>
...
FP|<16 hex chars>
```

- Lines are sorted; no timestamps are generated by the tool itself; nothing
  random; nothing locale-dependent. Same folder → same bytes.
- **The md5 is part of the fingerprint** (v1.1). Name + size + mtime is not
  enough: a file edited in place to the same length in the same second reads as
  "unchanged". When a backend cannot supply a hash the field is `-` and one
  constant line `HASH|missing|<n>` is added, so a degraded fingerprint is visible
  instead of silent.
- The watcher's **own** `STATUS_<agent>.md` is frozen to `<name>|self`. The
  heartbeat written every hour must not wake the agent that wrote it. Deletion
  is still visible, because the line disappears.
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

`--only-prefix URGENT_` restricts the watch to the urgent lane (§13).

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
| `lost_contact` | warn | heartbeat older than 90 minutes while not offline (v1.1) |
| `status_v10` | warn | status file lacks `protocol` / `heartbeat_at` (v1.1) |
| `urgent_without_prefix` | warn | `priority: urgent` but the name has no `URGENT_` prefix |
| `prefix_without_priority` | warn | `URGENT_` prefix but `priority` is not `urgent` |

## 12. Interop

- A human may edit any file, but editing a *task* breaks the "written once"
  invariant; prefer adding a `NOTE` file.
- Legacy or foreign files are ignored, never rewritten.
- Other tools may implement this spec as long as §5 produces identical states.

## 13. Protocol level 1.1 (2026-11-02)

Agreed with the other agents in the shared mailbox; this tool reports
`protocol: 1.1` in every STATUS file it writes. The deltas:

| area | rule | where |
|---|---|---|
| fingerprint | md5 is part of every watch line; `HASH\|missing\|<n>` when the backend has no hash | §10 |
| status | `protocol` + `heartbeat_at`; heartbeat ≤ 60 min, out of contact at 90 min | §9 |
| order | STATUS is updated *before* the RESULT / BLOCKED it describes | §9 |
| delivery | RESULT carries a manifest (file, folder, size, sha256); `--no-artifact "<reason>"` if there is no file | §7 |
| urgent | task names may start with `URGENT_`; a separate 5-minute watcher reads only those | §2 |
| credentials | client ids, secrets and tokens are never written into the mailbox or chat; polling volume needs your own OAuth client or a service account | §14 |

Two consequences worth stating plainly:

- A RESULT without a manifest is not a delivery, and text that only exists in a
  chat or a delegation summary is not a deliverable.
- An `URGENT_` file is the only case where the *file name* legitimately races a
  slow poller. `priority: urgent` alone does not.

## 14. Credentials and quota

The tool never handles credentials: `rclone` does, and its config lives outside
the mailbox (`.gitignore` excludes the checkout config too). Two operational
facts, learned the hard way:

- The OAuth client bundled with `rclone` is shared by every rclone user. It is
  rate-limited per project, and a multi-agent mailbox hits `403 Quota exceeded`
  well inside a normal polling day. Symptoms: `transport: rclone failed: … 403`.
- Fixes, in order of preference: a **service account** (no consent screen, no
  refresh expiry; just share the folder with its address), or your own OAuth
  desktop client (testing-mode clients expire refresh tokens in 7 days, so
  publish it or accept re-auth).

Do not put client ids, secrets or tokens in a task file, a STATUS file, a RESULT,
or a chat message. `lint` will flag assignments that look like secrets, but it is
a smoke detector.
