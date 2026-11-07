# PostBox-M

**Give another computer a job while you are nowhere near it.**

[![test](https://github.com/lx67621956-create/PostBox-M/actions/workflows/test.yml/badge.svg)](https://github.com/lx67621956-create/PostBox-M/actions/workflows/test.yml)
[![release](https://img.shields.io/github/v/release/lx67621956-create/PostBox-M)](https://github.com/lx67621956-create/PostBox-M/releases)
[![python](https://img.shields.io/badge/python-3.9%2B-blue)](pyproject.toml)
[![license](https://img.shields.io/badge/license-MIT-green)](LICENSE)

English · [中文](README.zh-CN.md) · [Español](README.es.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [Français](README.fr.md) · [Deutsch](README.de.md) · [Português](README.pt-BR.md)

![PostBox-M terminal demo](docs/demo.svg)

![PostBox-M viewer](docs/viewer.png)

<sub>`postbox serve` — read-only, runs on your own machine, reads the folder you already share. No account, no database, no deploy.</sub>

You are out, phone in hand. You tell the assistant on your phone: hand this to the machine at home. And it does — to the office computer in another city, to the box that is always on, to the desktop at home. That machine picks the task up, does the work, keeps the file where it is, and sends back a receipt: where it lives, how big it is, whether it matches.

How it travels is not your problem. One folder that several machines can see is enough: Google Drive, a private git repo, Syncthing, a USB stick. No server, no database, no account, no VPN.

## What you actually get

**1. Lightweight.**
The mailbox is a folder. No daemon, no database, nothing to watch at 3am. A few KB of text you can open, read, and copy away whole.

**2. No server to deploy.**
No port to open, no account to create, no IT ticket, no VPN. If the folder exists the system is up; if it does not, nothing breaks either.

**3. Many agents, one queue.**
Several machines and several different AIs work the same queue. One task, one owner: claiming is create-if-absent — six agents race, exactly one wins, the other five exit with code 3.

**4. Many storage backends.**
Google Drive, private git, WebDAV, SSH, S3, a local folder, a USB stick — seven backends, one set of commands. Use whichever you already have.

**5. Zero dependencies.**
Python standard library only, 3.9+. Nothing to compile, no lockfile, no supply chain to audit.

## Install

```bash
pip install "git+https://github.com/lx67621956-create/PostBox-M.git"
```

Or from source: `git clone … && uv tool install .`

## Sixty seconds

```bash
# machine A
postbox init --transport local --path "~/Dropbox/team-inbox" --agent alice
postbox new --to bob --title "weekly report" --ask "Five bullets, numbers only."

# machine B
postbox init --transport local --path "~/Dropbox/team-inbox" --agent bob
postbox inbox          # 1 task, from alice
postbox ack <id>
postbox result <id> --artifact weekly.md --text "Numbers for week 45, sources in the file"
```

That is the whole loop. Everything else — `watch`, `lint`, `doctor` — exists to
keep it running unattended.

## Pick a backend

`postbox providers` prints every option with a runnable command:

| preset | works in mainland China | what it is |
|---|---|---|
| `git` | yes | a private repo on Gitee / GitHub / your own VPS; one commit per write |
| `local` | yes | any folder your existing sync tool already replicates |
| `webdav` | yes | Nutstore (坚果云), Nextcloud, Alist |
| `sftp` | yes | a VPS you already own |
| `s3` | depends | MinIO, Cloudflare R2, Aliyun OSS |
| `gdrive` | no | Google Drive |
| `onedrive` / `dropbox` | no | OneDrive, Dropbox |

`local` needs no rclone, no OAuth, no account and no network — two checkouts
pointed at the same folder are a working mailbox, which is exactly how the test
suite runs.

## For the AI agents

A queue only works if every agent plays by the same rules, so the rules ship with
the tool:

```bash
postbox instructions --lang zh > AGENTS.md
```

It states the loop (ack before work, manifest in the result), the hard rules
(never edit another agent's file, never write a secret) and the exit codes that
mean "you lost the race" versus "the mailbox is unreachable". Paste it into the
system prompt, `AGENTS.md`, `CLAUDE.md` or a project skill.

<details>
<summary>All commands</summary>

| command | what it does |
|---|---|
| `init` | create `.postbox/config.json` and the mailbox |
| `new` | create a task (`--needs-owner` gates it, `--urgent` uses the 5-minute lane) |
| `dispatch tasks.json` | create a batch from JSON |
| `inbox` | mine, waiting for approval, and new replies on what I sent |
| `ls` / `show` | list / one task with its full event history |
| `ack` | claim (3 = taken, 5 = needs approval) |
| `note` | progress without changing state |
| `result` | deliver with `--artifact` (manifest + sha256) or `--no-artifact "<reason>"` |
| `blocked` | report a blocker and who you are asking |
| `owner-ok` / `owner-no` | record the human decision |
| `status` | refresh `STATUS_<agent>.md`; `--heartbeat` moves only the clock |
| `archive` | move finished work older than N days into `_archive/<year-month>/` (`--apply`) |
| `serve` | read-only web view on `127.0.0.1:8787`; `--host 0.0.0.0` exposes it to the network |
| `watch` | 0 unchanged, 10 changed, 11 degraded; `--only-prefix URGENT_` |
| `lint` | duplicate ids, orphan events, double results, leaked secrets, conflict copies |
| `doctor` | reachable **and** writable, proven with a create/read/delete probe |
| `providers` | every backend, marked for mainland China, with a runnable command |
| `instructions` | the rulebook for your agent (`--lang zh`) |

Exit codes: `0` ok, `2` usage, `3` conflict, `4` not found, `5` needs approval,
`6` lint errors, `10` changed, `11` degraded.

On disk, one task plus two receipts are three Markdown files, and the file name
carries the routing:

```
2026-11-02_TASK-20261102-1806-alice-to-bob-01_alice-to-bob_weekly-report.md
                                                    ..._ACK_bob.md
                                                    ..._RESULT_bob.md
```

</details>

## Fine print

Two things worth knowing: a synced folder only shows a file after the client has
delivered it, so poll slower than your sync latency; and when two edits collide a
desktop client writes `foo (1).md` beside `foo.md` — `lint` reports it, and the
original is untouched because nothing in this system is ever rewritten in place.

Deeper docs: [`docs/protocol.md`](docs/protocol.md) (the specification),
[`docs/design-notes.md`](docs/design-notes.md) (why it is built this way),
[`docs/why.md`](docs/why.md) (when to use it, and when not to).

Human output speaks Chinese too: `postbox --lang zh …`, or set `"lang": "zh"` once
in `.postbox/config.json` and every later command follows.

## About

Built by **闷闷AI说** — AI news, in Chinese, without the hype.

- YouTube: <https://www.youtube.com/@menmenAI>
- Bilibili: <https://space.bilibili.com/34234499>

MIT licensed.
