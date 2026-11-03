# PostBox-M — 给 Agent 的操作规则

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
