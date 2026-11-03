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
postbox result 20261102-1806-alice-to-bob-01 --artifact weekly.md --verified
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
| `new` | 发一个任务（`--needs-owner` 需要人批准；`--urgent` 走 5 分钟急件通道） |
| `dispatch tasks.json` | 一次派一批 |
| `inbox` | 我要干的、等我批准才能干的、我发出去的任务有新回复的 |
| `ls` / `show` | 列表 / 单任务全貌（含全部事件） |
| `ack` | 认领。重复认领退出码 3，需要批准但没批准退出码 5 |
| `note` | 记进度，不改状态 |
| `result` | 交付。`--artifact 文件` 自动生成清单（文件夹、文件名、大小、sha256）；没有文件就 `--no-artifact "理由"`。少于 20 个字会被拒 |
| `blocked` | 卡住了，同时写清在问谁什么 |
| `owner-ok` / `owner-no` | 人力批准 / 否决 |
| `status` | 刷新自己的 `STATUS_<agent>.md`；`--heartbeat` 只动心跳时间 |
| `watch` | 哑检查：指纹含 md5，无变化退出 0，有变化退出 10，掉线退出 11；`--only-prefix URGENT_` 只看急件 |
| `lint` | 审查整箱：重复 ID、孤儿回执、双人交付、空交付、僵尸心跳、泄露的密钥、同步冲突副本 |
| `doctor` | 这台机器通不通：可达 + **可写**（真建一个探针文件、读回来、删掉） |
| `providers` | 能用的后端一览，标了国内能不能用，每条都给了现成命令 |
| `instructions` | 打印给 AI 的操作规则（`--lang zh`） |

退出码有语义，方便脚本判断：`0` 正常、`2` 用法错、`3` 冲突、`4` 找不到、`5` 待批准、`6` lint 有错误、`10` 有变化、`11` 降级。

## 没有 Google Drive、也翻不了墙

邮箱就是一个文件夹。只要能把同一个文件夹在两台机器之间同步，就是合法后端；七个预设里只有三个跟 Google 有关。

```
$ postbox providers
PRESET    IN CN    NEEDS                      WHAT IT IS
local     yes      nothing                    你现有的同步工具在同步的那个文件夹
webdav    yes      rclone + 地址/应用密码       坚果云、Nextcloud、Alist
sftp      yes      rclone + ssh key            你自己那台 VPS
s3        depends  rclone + endpoint/key       MinIO、R2、阿里云 OSS（S3 网关）
gdrive    no       rclone + Google OAuth       Google Drive
onedrive  no       rclone + Microsoft OAuth    OneDrive
```

**新人第一条路是 `local`**：不装 rclone、不做 OAuth、不注册账号、不需要网络。两个 checkout 指向同一个文件夹，邮箱就成立了——测试套件就是这么跑的。

用桌面同步客户端要老实认两件事：

- 文件是"同步到了才算"，不是"对方写了就算"，轮询间隔必须大于同步延迟；
- 两边同时改同一个文件时，客户端会生成 `foo (1).md`。原名那个还是原名，PostBox 会忽略副本，`lint` 会报 `sync_conflict_copy`，但得有人真的去看。

## 给 AI 的说明书

邮箱能不能用，取决于几个 Agent 是不是遵守同一套规矩。`postbox instructions` 打的就是这本规矩：先认领再干活、不许改别人的文件、退出码 10 才代表"有变化"、RESULT 没有交付清单不算交付。

```
postbox instructions --lang zh > AGENTS.md
```

粘进系统提示词、`AGENTS.md`、`CLAUDE.md`、项目技能，或者你的 Agent 开机读的任何地方。`examples/AGENTS.md` 里是同一份。

**为什么必须给**：工具能管住"文件命名和状态"，管不住"模型想偷懒"。没有这份提示，模型最常犯的三个错是——不 ack 就开工（两个人做同一个任务）、`result` 里写一句"已完成"（没有交付物）、把 10 当成错误码然后重试一整天。规矩写进提示词，比在代码里加十道校验便宜。

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

## 五个设计取舍

**1. 状态是读出来的，不是写进去的。**
`state` 字段只在创建时写一次，之后就靠事件文件推导：有 ACK 就是 `ack`，有 RESULT 就是 `done`，有 BLOCKED 就是 `blocked`。没有"更新一下状态行"这个动作，也就不存在两个 Agent 同时改状态行、后写的覆盖先写的问题。

**2. 认领不是锁，是"一个任务只有一个负责人"。**
Google Drive 没有原子 create——实测 `rclone copyto --immutable` 在 Drive 上会**静默覆盖**（returncode 0），所以任何"我先占个坑"的写法都是假锁。PostBox-M 的做法是：任务只发给一个人；事件文件名带作者；写完之后**回读比对内容**，不是自己写的就报冲突。真正的互斥留给"一任务一负责人"这条规则，不靠 API 承诺。

**3. 轮询器必须逐字节稳定。**
`postbox watch` 的 stdout 在没有变化时和上一次完全相同。失败时不打印带时间戳的报错（那会让每一轮都不一样，每轮都唤醒模型），而是回放上次基线 + 一行**恒定**的 `STATUS|DEGRADED|...`；连续两次失败才打这一行，恢复后这一行消失。一次掉线只唤醒一次，不是一千次。

**4. 幂等放在应用层。**
传输层的 `create` 遇到同名文件就是冲突，不猜。是不是"我自己的重试"由上层判断——事件的 front matter 里带 `instance: <pid>-<host>`，字节完全相同才算自己重试。把幂等塞进 `create` 会让并发抢同一个任务时全部"成功"。

**5. 指纹必须带哈希，交付必须带清单。**
只比「文件名 + 大小 + 修改时间」会漏掉同一秒内被改成同样长度的文件——这种漏检最阴，因为一切看起来都没变。所以指纹里加 md5；拿不到哈希时输出里会出现 `HASH|missing|n`，宁可难看也不假装。同理，`result` 不允许只说"已完成"：`--artifact` 会把文件、目录、大小、sha256 写成表格，没有文件就必须 `--no-artifact "理由"`。结论写在聊天里、委派摘要里，都不算交付。

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

由 **闷闷AI说** 维护。频道做 AI 科技资讯，新东西第一时间讲给您听；这个工具是顺手把几台机器上几个 Agent 的交接流程固化下来的产物。

- YouTube：<https://www.youtube.com/@menmenAI>
- B站：<https://space.bilibili.com/34234499>

MIT 协议，随便用。
