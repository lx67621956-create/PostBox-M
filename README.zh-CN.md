# PostBox-M

**把你们本来就共享的那个网盘文件夹，变成 Agent 之间收发任务的邮箱。**

几台机器、几个 AI Agent，互相连不上：一个在你笔记本上，一个在台式机，一个在云服务器。它们唯一的共同点是一个共享文件夹。PostBox-M 就靠这一个文件夹做任务指派和交接——不用服务器、不用数据库、不用把它们挂到同一个局域网，也不用给每个 Agent 发一把 API key。

写这个工具的直接原因：多个 Agent 靠人来回搬任务，搬到第四五个的时候一定会漏。漏的方式还很隐蔽——任务文件被覆盖了、同一件事被两个 Agent 各做一遍、做完了没人知道、改过的版本分不清哪个是新的。

## 它解决的问题，按真实痛感排序

1. **任务能被发现，而且只被一个人认领。** 任务文件写清给谁、要什么、验收标准；接收方 `ack` 认领，第二个来认领的会被拒绝（退出码 3）。
2. **记录不会被覆盖。** 原任务文件一旦写出永不修改。回执、结果、阻塞都是**另建文件**，文件名带作者。谁写的谁的，冲突了也不丢东西。
3. **不需要人批准的事不会偷偷开工。** 任务写 `needs_owner_confirm: yes`，接收方 `ack` 直接被拒（退出码 5），必须有人先跑一次 `owner-ok`。
4. **轮询不烧钱。** `postbox watch` 没有变化时输出**逐字节相同**，监控端（cron、systemd、Agent 调度器）比对 stdout 就能跳过整个模型调用。
5. **网盘抽风不会变成假警报。** 限流、断网、半途崩溃，队列不会被写脏，基线不会被错误覆盖。

## 安装

```bash
uv tool install postbox-m     # 或 pip install postbox-m
```

零 Python 依赖，只用标准库。网盘走 rclone（已在用的不用重配 OAuth），或者干脆用本地目录 + Syncthing / 坚果云 / Dropbox / iCloud / U 盘。

## 五分钟跑通

两台机器、一个共享文件夹。

```bash
# A 机器（Google Drive 上先建一个空文件夹 team/inbox）
postbox init --transport rclone --remote gdrive:team/inbox --agent alice

postbox new --to bob --title "每周复盘" \
  --ask "5 条要点，每条带官方来源和日期" \
  --accept "5 条，不许空话，链接可点开"
```

```bash
# B 机器
postbox init --transport rclone --remote gdrive:team/inbox --agent bob

postbox inbox
# todo →
# ID                             STATE  FROM   AGE  TITLE
# 20261102-1806-alice-to-bob-01  new    alice  1m   每周复盘

postbox ack 20261102-1806-alice-to-bob-01 --note "收到，18 点前给"
postbox result 20261102-1806-alice-to-bob-01 --verified --file weekly.md
```

```bash
# A 机器：看回执
postbox inbox          # replies on tasks you sent →
postbox show 20261102-1806-alice-to-bob-01
postbox ls --all
```

本地目录（不用 Google Drive）：

```bash
postbox init --transport local --path /path/to/shared-folder --agent alice
```

## 命令

| 命令 | 干什么 |
|---|---|
| `init` | 建 `.postbox/config.json` 和邮箱目录 |
| `new` | 发一个任务（`--needs-owner` 表示需要人批准） |
| `dispatch tasks.json` | 一次派一批 |
| `inbox` | 我要干的、等我批准才能干的、我发出去的任务有新回复的 |
| `ls` / `show` | 列表 / 单任务全貌（含全部事件） |
| `ack` | 认领。重复认领退出码 3，需要批准但没批准退出码 5 |
| `note` | 记进度，不改状态 |
| `result` | 交付。少于 20 个字会被拒（"已完成"不算交付） |
| `blocked` | 卡住了，同时写清在问谁什么 |
| `owner-ok` / `owner-no` | 人力批准 / 否决 |
| `status` | 刷新自己的 `STATUS_<agent>.md` 心跳 |
| `watch` | 哑检查：无变化退出 0，有变化退出 10，掉线退出 11 |
| `lint` | 审查整箱：重复 ID、孤儿回执、双人交付、空交付、僵尸心跳、泄露的密钥 |
| `doctor` | 这台机器通不通 |

退出码有语义，方便脚本判断：`0` 正常、`2` 用法错、`3` 冲突、`4` 找不到、`5` 待批准、`6` lint 有错误、`10` 有变化、`11` 降级。

## 文件夹里到底多了什么

一个任务 + 两次回执 = 三个文件，全都是 Markdown：

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

# 每周复盘
...
```

```markdown
---
kind: ACK
agent: bob
at: 2026-11-02 18:07:32 +0800
instance: 11528-GothicPC
---

收到，今天 18 点前给。
```

文件名长得丑，但它是格式的一部分：

```
2026-11-02_TASK-20261102-1806-alice-to-bob-01_alice-to-bob_每周复盘.md
                                                 ..._ACK_bob.md
                                                 ..._RESULT_bob.md
```

任务 ID 里带发起方、接收方和时间，事件文件以任务文件名为前缀。好处是可以直接在 Google Drive 手机版里看，也可以用一个编辑器人工补救；坏处是名字长。我选了好补救。

## 四个设计取舍

**1. 状态是读出来的，不是写进去的。**
`state` 字段只在创建时写一次，之后就靠事件文件推导：有 ACK 就是 `ack`，有 RESULT 就是 `done`，有 BLOCKED 就是 `blocked`。没有"更新一下状态行"这个动作，也就不存在两个 Agent 同时改状态行、后写的覆盖先写的问题。

**2. 认领不是锁，是"一个任务只有一个负责人"。**
Google Drive 没有原子 create——实测 `rclone copyto --immutable` 在 Drive 上会**静默覆盖**（returncode 0），所以任何"我先占个坑"的写法都是假锁。PostBox-M 的做法是：任务只发给一个人；事件文件名带作者；写完之后**回读比对内容**，不是自己写的就报冲突。真正的互斥留给"一任务一负责人"这条规则，不靠 API 承诺。

**3. 轮询器必须逐字节稳定。**
`postbox watch` 的 stdout 在没有变化时和上一次完全相同。失败时不打印带时间戳的报错（那会让每一轮都不一样，每轮都唤醒模型），而是回放上次基线 + 一行**恒定**的 `STATUS|DEGRADED|...`；连续两次失败才打这一行，恢复后这一行消失。一次掉线只唤醒一次，不是一千次。

**4. 幂等放在应用层。**
传输层的 `create` 遇到同名文件就是冲突，不猜。是不是"我自己的重试"由上层判断——事件的 front matter 里带 `instance: <pid>-<host>`，字节完全相同才算自己重试。把幂等塞进 `create` 会让并发抢同一个任务时全部"成功"。

## 边界

- **不是实时通信。** 最快等于网盘同步延迟（Google Drive 通常几秒），不适合毫秒级协调。
- **不发放权限。** 文件里写"已批准"不等于批准；`needs_owner_confirm` 只是让流程无法绕过人，不验证人是谁。
- **不保证原子。** 网盘没有事务，只有回读校验和单负责人规则。两个实例故意抢同一个任务，最后一秒内仍可能双写。
- **不该放的东西。** 密码、验证码、卡号、身份证、私钥。`lint` 会扫常见密钥格式并报 error，但别指望它兜底。

## 兼容

文件名沿用一套已经在生产里跑了大半年的约定（`YYYY-MM-DD_TASK-<id>_<from>to<to>_<标题>.md`、`_ACK_<人>.md`、`STATUS_<人>.md`），所以已有的共享目录可以直接接。别人的文件、旧格式的说明文档不会被当成任务，也不会被改动——不认识的直接跳过。

## 文档

- [`docs/protocol.md`](docs/protocol.md) — 规范：命名、front matter、状态机、并发规则
- [`docs/design-notes.md`](docs/design-notes.md) — 为什么这么设计，以及踩过的坑

## 关于

由 **闷闷AI说** 维护。最初是为了让几个跑在不同机器上的 Agent 别再靠人转述任务，后来发现"共享文件夹 + 不可变事件"这套在什么网盘上都成立，就抽成了工具。

MIT 协议，随便用。
