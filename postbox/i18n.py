"""Human language for the messages people actually read.

Two mechanisms, both deliberately dumb:

* ``tpl(en, zh)`` for strings we print ourselves — one call site, no lookup table.
* ``RULES`` for the errors raised deep in the code: the sentence is matched as-is
  and swapped for Chinese. A missing rule falls through to English, so a new
  error message can never crash the translator or disappear.

Language comes from ``POSTBOX_LANG``, then ``--lang``, then ``lang`` in the
config, then English.
"""
from __future__ import annotations

import os
import re
from typing import List, Tuple

LANG = (os.environ.get("POSTBOX_LANG") or "").strip().lower()


def set_lang(value: str) -> None:
    global LANG
    if value:
        LANG = value.strip().lower()


def is_zh() -> bool:
    return LANG.startswith("zh")


def tpl(en: str, zh: str) -> str:
    return zh if is_zh() else en


WORDS = {
    "error": ("error", "错误"),
    "conflict": ("conflict", "冲突"),
    "transport": ("transport", "传输"),
    "nothing": ("nothing for %s", "%s 这里没有待办"),
    "empty": ("(empty)", "（空）"),
    "dispatched": ("%d task(s) dispatched", "已派出 %d 个任务"),
    "initialised": ("initialised %s", "已初始化 %s"),
    "mailbox": ("mailbox   %s", "邮箱      %s"),
    "agent": ("agent     %s", "本机身份  %s"),
    "next": ('next      postbox new --to <peer> --title "..." --ask "..."',
             '下一步    postbox new --to <对方> --title "..." --ask "..."'),
}

RULES: List[Tuple[str, str]] = [
    (r"^no \.postbox/config\.json found \(run `postbox init` first\)$",
     "没有找到 .postbox/config.json（先跑 `postbox init`）"),
    (r"^(.*) was already accepted by (.*) — do not work on it twice\.$",
     r"\1 已经被 \2 认领了 —— 不要重做"),
    (r"^(.*) was already accepted by you \((.*)\)\. Append a note instead\.$",
     r"\1 是你自己认领的（\2）。要补话请用 note"),
    (r"^(.*) needs owner confirmation first \(`postbox owner-ok (.*)`\)$",
     r"\1 还需要人批准：先跑 `postbox owner-ok \2`"),
    (r"^(.*) is already done — write a NOTE instead$",
     r"\1 已经交付完成 —— 有补充请写 NOTE"),
    (r"^artifact not found: (.*)$", r"交付物不存在：\1"),
    (r"^nothing to write: pass --text/--file \(or (.*) on stdin\)$",
     r"没有内容可写：给 --text/--file（或用 stdin 的 \1）"),
    (r"^(.+) exists \(use --force to rewrite\)$", r"\1 已存在（要重写请加 --force）"),
    (r"^--transport rclone needs --remote, e\.g\. (.*)$",
     r"--transport rclone 需要 --remote，例如 \1"),
    (r"^--transport git needs a checkout: (.*)$",
     r"--transport git 需要一个仓库：\1"),
    (r"^(.+) is not a git checkout — clone the mailbox repo there first$",
     r"\1 不是 git 仓库 —— 先把邮箱仓库 clone 到那里"),
    (r"^rclone is not on PATH; set rclone_bin in \.postbox/config\.json \(or POSTBOX_RCLONE_BIN\) to the full path$",
     "找不到 rclone：把 rclone_bin 写进 .postbox/config.json（或设 POSTBOX_RCLONE_BIN）指向完整路径"),
    (r"^cannot determine the branch of (.*)$", r"判断不出 \1 的分支"),
    (r"^too many (.*) files for (.*)$", r"\2 的 \1 文件太多了"),
    (r"^could not allocate a task id \(too many collisions\)$", "分配不到任务 ID（撞得太多）"),
    (r"^(.+) must contain a JSON array of tasks$", r"\1 里必须是任务的 JSON 数组"),
    (r"^every task needs 'to' and 'title': (.*)$", r"每个任务都要有 'to' 和 'title'：\1"),
    (r"^unknown task id: (.*)$", r"找不到这个任务：\1"),
]

_COMPILED = [(re.compile(p), r) for p, r in RULES]


def tr(text: str) -> str:
    """Translate a full English sentence if we know it; otherwise return it as-is."""
    if not is_zh() or not text:
        return text
    for pattern, replacement in _COMPILED:
        if pattern.match(text):
            return pattern.sub(replacement, text)
    return text
