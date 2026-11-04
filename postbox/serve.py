"""Read-only web view of a mailbox — `postbox serve`.

Deliberately not a service: it binds 127.0.0.1, it never writes, and it holds no
state of its own. The folder stays the only source of truth, so a viewer can be
started on any machine that can read the folder and stopped without consequence.

If you point it at 0.0.0.0 you are publishing the contents of your mailbox to
your network; the server says so before it starts.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional

from . import core, i18n
from .lint import lint
from .state import OPEN_STATES

CACHE_SECONDS = 5.0


def _when(raw: str, offset_hours: float = 8.0) -> str:
    """Every timestamp leaves here as local time with an explicit offset.

    Backends disagree: the local one reports UTC without a timezone, front matter
    carries `+0800`, git reports nothing at all. The page should not have to know.
    """
    if not raw:
        return ""
    stamp = core.parse_ts(raw)
    if stamp is None:
        try:
            stamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return raw
        if stamp.tzinfo is None:                 # local backend mtimes are UTC
            stamp = stamp.replace(tzinfo=timezone.utc)
    zone = timezone(timedelta(hours=offset_hours))
    return stamp.astimezone(zone).isoformat(timespec="seconds")


def _shorten(path: str, keep: int = 2) -> str:
    """`C:\\Users\\me\\...\\viewdemo\\mail` → `…/viewdemo/mail` — no need to publish
    someone's home directory to a browser tab."""
    parts = [p for p in path.replace("\\", "/").split("/") if p]
    if len(parts) <= keep + 1:
        return path
    return "…/" + "/".join(parts[-keep:])


class Snapshot:
    """Rebuild the whole picture at most once every CACHE_SECONDS."""

    def __init__(self, cfg, sla_hours: int = 48):
        self.cfg = cfg
        self.sla_hours = sla_hours
        self._lock = threading.Lock()
        self._at = 0.0
        self._payload: Optional[Dict[str, Any]] = None

    def get(self) -> Dict[str, Any]:
        with self._lock:
            if self._payload is not None and time.time() - self._at < CACHE_SECONDS:
                return self._payload
            try:
                self._payload = self._build()
            except Exception as exc:                      # a viewer must not die
                self._payload = {"error": str(exc), "tasks": [], "agents": [],
                                 "findings": [], "generated_at": core.now()}
            self._at = time.time()
            return self._payload

    def _build(self) -> Dict[str, Any]:
        from .cli import mailbox                     # avoids an import cycle

        cfg = self.cfg
        box = mailbox(cfg).sync()
        now = core.fmt_ts(core.now(cfg.utc_offset_hours))

        tasks = [self._task(entry) for entry in box.entries]
        tasks.sort(key=lambda t: t["updated"], reverse=True)

        open_counts: Dict[str, int] = {}
        for t in tasks:
            if t["state"] in OPEN_STATES:
                open_counts[t["to"]] = open_counts.get(t["to"], 0) + 1

        agents = []
        for name, meta in sorted(box.statuses().items()):
            beat = meta.get("heartbeat_at", "")
            stale = False
            if beat:
                try:
                    age = core.parse_ts(now) - core.parse_ts(beat)
                    stale = age.total_seconds() > core.HEARTBEAT_STALE_MIN * 60
                except Exception:
                    stale = False
            agents.append({
                "name": name,
                "state": meta.get("state", "?"),
                "device": meta.get("device", ""),
                "heartbeat_at": beat,
                "protocol": meta.get("protocol", ""),
                "stale": stale,
                "open": open_counts.get(name, 0),
            })

        findings = [{"level": level, "code": code, "message": msg}
                    for level, code, msg in lint(box, self.sla_hours)]

        return {
            "generated_at": now,
            "agent": cfg.agent,
            "transport": cfg.transport,
            "where": _shorten(cfg.remote or cfg.resolve(cfg.path)),
            "tasks": tasks,
            "agents": agents,
            "findings": findings,
        }

    def _task(self, entry) -> Dict[str, Any]:
        spot = self.cfg.utc_offset_hours
        task = entry.task
        result = None
        finished = entry.events_of("RESULT")
        if finished:
            event = finished[-1]
            result = {
                "agent": event.agent,
                "at": _when(event.meta.get("at", "") or event.mtime, spot),
                "summary": (event.body or "").strip()[:600],
                "artifact": event.meta.get("artifact", ""),
                "sha256": event.meta.get("sha256", ""),
                "bytes": event.meta.get("bytes", ""),
                "verified": event.meta.get("verified", ""),
            }
        events = [{
            "kind": event.kind,
            "agent": event.agent,
            "at": _when(event.meta.get("at", "") or event.mtime, spot),
            "text": (event.body or "").strip()[:500],
        } for event in entry.events]
        return {
            "id": task.task_id,
            "title": task.title,
            "from": task.sender,
            "to": task.recipient,
            "state": entry.state,
            "updated": _when(entry.updated, spot),
            "priority": task.priority,
            "urgent": task.urgent,
            "needs_owner": task.needs_owner,
            "ask": (task.body or "").strip()[:800],
            "events": events,
            "result": result,
        }


PAGE = r"""<!doctype html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>PostBox-M — __WHERE__</title>
<style>
  :root{--bg:#14110f;--card:#1c1815;--line:#302822;--ink:#f2e9df;--dim:#9c8f81;--accent:#FF6B35;
        --ok:#5fbf7f;--warn:#e8b04b;--bad:#e5645a;}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);
       font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}
  header{padding:22px 28px 14px;border-bottom:1px solid var(--line);display:flex;
         align-items:baseline;gap:14px;flex-wrap:wrap}
  h1{font-size:17px;margin:0;letter-spacing:.04em}
  h1 span{color:var(--accent)}
  .path{color:var(--dim);font:12px ui-monospace,SFMono-Regular,Consolas,monospace;
        overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:56vw}
  .stamp{margin-left:auto;color:var(--dim);font-size:12px}
  main{padding:20px 28px 60px;max-width:1240px;margin:0 auto}
  .agents{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:20px}
  .agent{background:var(--card);border:1px solid var(--line);border-radius:10px;
         padding:10px 14px;min-width:150px}
  .agent b{font-size:14px}
  .agent .meta{color:var(--dim);font-size:12px;margin-top:2px}
  .dot{display:inline-block;width:7px;height:7px;border-radius:50%;margin-right:6px;vertical-align:1px}
  .banner{border:1px solid var(--line);background:#201a15;border-radius:10px;padding:10px 14px;
          margin-bottom:18px;font-size:13px}
  .banner b{color:var(--warn)}
  table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);
        border-radius:12px;overflow:hidden}
  th{text-align:left;font-weight:500;font-size:12px;color:var(--dim);padding:10px 14px;
     border-bottom:1px solid var(--line);text-transform:uppercase;letter-spacing:.06em}
  td{padding:11px 14px;border-bottom:1px solid var(--line);vertical-align:top}
  tr:last-child td{border-bottom:0}
  tbody tr{cursor:pointer}
  tbody tr:hover{background:#221c18}
  tbody tr.on{background:#26190f;box-shadow:inset 3px 0 0 var(--accent)}
  .id{font:12px ui-monospace,SFMono-Regular,Consolas,monospace;color:#a1927f}
  .pill{display:inline-block;padding:2px 9px;border-radius:999px;font-size:12px;
        border:1px solid var(--line)}
  .s-new{color:#8fb7d6}.s-ack{color:#c9a2e0}.s-working{color:var(--warn)}
  .s-question,.s-blocked{color:var(--bad)}.s-done{color:var(--ok)}.s-waiting_owner{color:#d9c07a}
  #detail{margin-top:22px;background:var(--card);border:1px solid var(--line);border-radius:12px;
          padding:18px 20px;display:none}
  #detail h2{font-size:16px;margin:0 0 4px}
  #detail .ask{white-space:pre-wrap;color:#dcd2c6;margin:10px 0 16px}
  .tl{list-style:none;padding:0;margin:0}
  .tl li{padding:8px 0 8px 18px;border-left:1px solid var(--line);position:relative}
  .tl li:before{content:"";position:absolute;left:-4px;top:14px;width:7px;height:7px;
                border-radius:50%;background:var(--line)}
  .tl .k{font:12px ui-monospace,monospace;color:var(--accent)}
  .tl .t{color:var(--dim);font-size:12px;margin-left:8px}
  .mono{font:12px ui-monospace,SFMono-Regular,Consolas,monospace;color:#cfc4b7}
  .empty{color:var(--dim);padding:26px;text-align:center}
  footer{color:#5f554c;font-size:11px;text-align:center;padding:0 0 30px}
</style></head><body>
<header>
  <h1>Post<span>Box</span>-M</h1>
  <div class="path" id="where">__WHERE__</div>
  <div class="stamp" id="stamp">…</div>
</header>
<main>
  <div class="agents" id="agents"></div>
  <div id="banner"></div>
  <table>
    <thead><tr><th>任务</th><th>状态</th><th>从 → 到</th><th>更新</th></tr></thead>
    <tbody id="rows"><tr><td colspan="4" class="empty">读不到邮箱</td></tr></tbody>
  </table>
  <div id="detail"></div>
  <footer>只读视图 · 每 10 秒刷新 · 数据来自共享文件夹本身</footer>
</main>
<script>
let DATA=null, PICK=null;
const esc=s=>String(s==null?"":s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const LABEL={new:"待认领",waiting_owner:"等批准",ack:"已认领",working:"进行中",question:"有疑问",blocked:"卡住",done:"已完成"};
const MOOD={online:"在线",idle:"空闲",working:"忙",blocked:"卡住",offline:"离线"};
const label=s=>LABEL[s]||s;
function ago(ts){
  if(!ts) return "—";
  let s=String(ts).trim().replace(" ","T").replace(" ","")
        .replace(/([+-]\d{2})(\d{2})$/, "$1:$2");
  if(!/[Zz+]/.test(s.slice(10))) s+="+08:00";
  const d=new Date(s), sec=(Date.now()-d.getTime())/1000;
  if(isNaN(sec)) return ts;
  if(sec<60) return Math.max(1,Math.round(sec))+" 秒前";
  if(sec<3600) return Math.round(sec/60)+" 分钟前";
  if(sec<86400) return Math.round(sec/3600)+" 小时前";
  return Math.round(sec/86400)+" 天前";
}
function render(){
  if(!DATA) return;
  document.getElementById("where").textContent=(DATA.transport||"")+" · "+(DATA.where||"");
  document.getElementById("stamp").textContent="更新于 "+ago(DATA.generated_at);
  const ag=DATA.agents||[];
  document.getElementById("agents").innerHTML = ag.length? ag.map(a=>
    `<div class="agent"><b><span class="dot" style="background:${a.stale?'#e5645a':'#5fbf7f'}"></span>${esc(a.name)}</b>
     <div class="meta">${MOOD[a.state]||esc(a.state)} · ${a.open} 个在办</div>
     <div class="meta">最后活跃 ${ago(a.heartbeat_at)}${a.stale?" · 已失联":""}</div></div>`).join("")
    : `<div class="agent"><b>还没有 Agent 报到</b><div class="meta">STATUS_*.md 为空</div></div>`;
  const f=DATA.findings||[];
  document.getElementById("banner").innerHTML = f.length
    ? `<div class="banner"><b>lint 有 ${f.length} 条</b><br>`+
      f.slice(0,6).map(x=>`<span class="mono">${esc(x.code)}</span> ${esc(x.message)}`).join("<br>")+"</div>" : "";
  const rows=DATA.tasks||[];
  document.getElementById("rows").innerHTML = rows.length? rows.map(t=>
    `<tr data-id="${esc(t.id)}" class="${PICK===t.id?'on':''}">
       <td><div>${esc(t.title)}</div><div class="id">${esc(t.id)}</div></td>
       <td><span class="pill s-${esc(t.state)}">${esc(label(t.state))}</span>${t.urgent?' <span class="pill" style="color:#e5645a">急</span>':''}</td>
       <td class="id">${esc(t.from)} → ${esc(t.to)}</td>
       <td class="id">${ago(t.updated)}</td></tr>`).join("")
    : `<tr><td colspan="4" class="empty">队列是空的</td></tr>`;
  document.querySelectorAll("tbody tr[data-id]").forEach(tr=>tr.onclick=()=>{
    PICK=tr.dataset.id; render(); show(PICK);
  });
  if(PICK) show(PICK);
}
function show(id){
  const t=(DATA.tasks||[]).find(x=>x.id===id); const box=document.getElementById("detail");
  if(!t){box.style.display="none";return;}
  const ev=(t.events||[]).map(e=>`<li><span class="k">${esc(e.kind)}</span>
      <span class="t">${esc(e.agent)} · ${esc(e.at)}</span>
      <div>${esc(e.text)}</div></li>`).join("");
  const r=t.result? `<div class="mono" style="margin-top:14px">交付 · ${esc(t.result.artifact||"—")} ·
      ${esc(t.result.bytes||"?")} bytes · sha256 ${esc((t.result.sha256||"—").slice(0,16))}…
      ${t.result.verified?"✓ verified":""}</div>`:"";
  box.style.display="block";
  box.innerHTML=`<h2>${esc(t.title)}</h2>
    <div class="id">${esc(t.id)} · ${esc(t.from)} → ${esc(t.to)} · ${esc(label(t.state))} · 更新 ${esc(t.updated)}</div>
    <div class="ask">${esc(t.ask)}</div>
    <ul class="tl">${ev}</ul>${r}`;
}
async function tick(){
  try{ const r=await fetch("/api/state",{cache:"no-store"}); DATA=await r.json(); render(); }
  catch(e){ document.getElementById("stamp").textContent="读不到"; }
}
tick(); setInterval(tick,10000);
</script></body></html>
"""


class Handler(BaseHTTPRequestHandler):
    server_version = "postbox-viewer"
    snapshot: Snapshot = None            # set by serve()
    page: bytes = b""

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:                                   # noqa: N802
        if self.path in ("/", "/index.html"):
            self._send(200, self.page, "text/html; charset=utf-8")
        elif self.path.split("?")[0] == "/api/state":
            payload = json.dumps(self.snapshot.get(), ensure_ascii=False, indent=1)
            self._send(200, payload.encode("utf-8"), "application/json; charset=utf-8")
        elif self.path == "/favicon.ico":
            self._send(204, b"", "image/x-icon")
        else:
            self._send(404, b"not found", "text/plain; charset=utf-8")

    def do_POST(self) -> None:                                  # noqa: N802
        self._send(405, b"read-only", "text/plain; charset=utf-8")

    do_PUT = do_DELETE = do_PATCH = do_POST

    def log_message(self, *_args) -> None:                      # keep the terminal quiet
        pass


def serve(cfg, host: str = "127.0.0.1", port: int = 8787,
          open_browser: bool = False, sla_hours: int = 48) -> int:
    snapshot = Snapshot(cfg, sla_hours)
    where = cfg.remote or cfg.resolve(cfg.path)
    page = PAGE.replace("__WHERE__", where)

    handler = type("BoundHandler", (Handler,), {
        "snapshot": snapshot,
        "page": page.encode("utf-8"),
    })
    httpd = ThreadingHTTPServer((host, port), handler)
    url = "http://%s:%d/" % (host if host != "0.0.0.0" else "127.0.0.1", port)

    print(i18n.tpl("serving %s (read-only)", "只读视图 %s") % url)
    print(i18n.tpl("   mailbox %s", "   邮箱 %s") % where)
    if host not in ("127.0.0.1", "localhost", "::1"):
        if i18n.is_zh():
            print("   注意：%s 不是本机回环 —— 能连上这个端口的人都能看到你的任务" % host)
        else:
            print("   warning: %s is not loopback — anyone who can reach this "
                  "port can read your tasks" % host)
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0
