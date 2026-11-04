# Why PostBox-M, and when not to use it

> 三句话版：多个 Agent 在不同机器上，没有公网入口、不想养中间件，就用它；又需要毫秒级协同、或者要真的权限控制，就别用。它是**任务邮箱**，不是消息总线。

## The problem it solves

You have two or more agents that cannot talk to each other: one on a laptop, one on
a desktop, one on a VPS, one inside a CI runner. They already share one thing — a
folder. Asking a human to copy tasks between them works for two tasks and fails at
five, in ways that are hard to notice:

- the same job is done twice by two agents;
- a result is pasted into a chat and lost;
- the newest version is guessed instead of known;
- nobody can tell whether the job is still running or quietly dead.

PostBox-M turns that folder into a queue with **one owner per task** and **an
append-only history**, using nothing but files.

## What it is, in one table

| | PostBox-M |
|---|---|
| transport | the folder you already share (Drive, git, WebDAV, SFTP, S3, LAN) |
| servers to run | none |
| accounts to create | none (whatever your folder already needs) |
| claim semantics | `create-if-absent`; losers get exit 3 |
| history | one immutable file per action; `git log` proves it on the git backend |
| delivery | a manifest with size + sha256, not a sentence |
| idle cost | zero tokens: `watch` is byte-stable and exits 0 |
| language | any — the wire format is Markdown with a front matter block |

## Against the alternatives

**Manual delegation inside one agent session.** Fine for one agent, one machine.
The moment work must survive a restart, or two agents must not step on each other,
you need something outside the model's context.

**MCP.** Different layer: MCP connects a model to *tools*. It says nothing about
who owns a task, what "done" means, or what happens when two agents pick up the
same job. PostBox-M is where that coordination lives; an agent can call both.

**A2A and other agent-to-agent protocols.** Designed for agents that can reach each
other over HTTP with discovery and identity. If your boxes are behind NAT, have no
public endpoint, or simply are not online at the same time, that assumption fails
before the first message. A folder does not require the other side to be up.

**Redis / SQS / RabbitMQ / Kafka.** Real queues, and the right answer if you
already run one. They also mean a broker to deploy, credentials to distribute, and
an agent that must be connected to consume. For a handful of agents doing hourly
work, the broker is more moving parts than the work.

**A shared database.** Works, but you end up writing the queue yourself: schema,
claim transactions, retries, and a migration path when the schema changes. And
every agent needs database credentials — a much larger blast radius than a folder.

**Plain git commits, by hand.** Close in spirit: files, history, no server. What is
missing is the claim rule and the naming convention, so two agents still overwrite
each other, and "is this task done?" depends on whoever reads the log.

## When not to use it

- **Sub-second coordination.** Latency is your sync layer: seconds on a cloud
  drive, near-instant on git or a LAN share, but never a message bus.
- **Large binaries.** A folder of Markdown is the design; a 2 GB video per task
  will make every listing slow on a cloud backend.
- **Authorization.** A file that says `owner_ok` is a record, not a permission
  system. `needs_owner_confirm` stops an agent from skipping the human; it cannot
  prove who the human was.
- **Secrets.** `lint` recognises common key formats and shouts, but the mailbox is
  shared by design. Do not put credentials there.

## Picking a backend

| if you have | use | why |
|---|---|---|
| two machines, no account, no network | `local` + any sync client | zero setup, works offline |
| a private repo | `git` | free audit trail, one commit per action |
| Nutstore / Nextcloud | `webdav` | works from mainland China without a VPN |
| a VPS | `sftp` | you already have the key |
| Google Drive | `gdrive` | convenient, needs access to Google |
| object storage | `s3` | cheap for many small files |

`postbox providers` prints the exact command for each.

## The four primitives

Everything above rests on four operations a backend must provide:

1. `list` — everything in the folder, with a content hash;
2. `read` — one file;
3. `create-if-absent` — the claim primitive, and the only race that matters;
4. `replace-own-file` — used only for `STATUS_<agent>.md`, which each agent owns.

Add a naming convention and three invariants — a task is written once, every action
is a new file, one task has one owner — and the whole protocol follows. That is why
the same code runs on a USB stick and on Google Drive.
