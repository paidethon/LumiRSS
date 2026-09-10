#!/usr/bin/env python3
"""PoC 10-agent-workbench server: tool-loop agent with SSE streaming,
citations of real Lumi search results, and a human-approval-gated write tool.

Deterministic mock LLM (scripted tool calls — no paid API) drives the loop;
the search tool returns REAL data from the running dev BFF on :8000.

Run: uv run --with fastapi --with uvicorn --with httpx python poc_agent.py &
then open http://127.0.0.1:18901/ (driver: agent_driver.py).
"""
from __future__ import annotations

import asyncio
import json

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

LUMI_BFF = "http://127.0.0.1:8000"
PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Agent PoC</title>
<style>body{font:14px system-ui;max-width:720px;margin:2rem auto}
.msg{padding:.4rem .6rem;border-left:3px solid #88f;margin:.4rem 0}
.tool{background:#f4f4ff;font-family:monospace;font-size:12px}
.approval{background:#fff7e0;border:1px solid #e0c060;padding:.5rem;margin:.4rem 0}
button{padding:.4rem 1rem;margin:.2rem}</style></head><body>
<h2>LumiRSS Agent 工作台 PoC</h2>
<div id="log"></div>
<div id="approval" style="display:none" class="approval">工具 <b>save_bookmark</b> 想把「Quantization reduces memory…」加入工作区「AI 研究」
  <button onclick="decide('approved')">批准</button>
  <button onclick="decide('denied')">拒绝</button>
</div>
<button id="ask">问: 帮我找 vLLM V1 相关文章,并保存量化笔记到工作区</button>
<script>
function log(kind,text){const d=document.createElement('div');d.className=kind;d.textContent=text;
  document.getElementById('log').appendChild(d);}
async function decide(v){await fetch('/decide',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({v})});
  document.getElementById('approval').style.display='none';}
document.getElementById('ask').onclick=async()=>{
  document.getElementById('ask').disabled=true;
  const es=new EventSource('/agent/stream');
  es.onmessage=e=>{const m=JSON.parse(e.data);log(m.kind,m.text);
    if(m.kind==='approval')document.getElementById('approval').style.display='block';
    if(m.done)es.close();};
};
</script></body></html>"""

app = FastAPI()
decision_q: asyncio.Queue = asyncio.Queue()


async def tool_search(query: str) -> list[dict]:
    """REAL read-only tool: queries the actual running Lumi BFF."""
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(f"{LUMI_BFF}/api/v1/search", params={"q": query, "limit": 3})
        r.raise_for_status()
        return [
            {"entryRef": it["entryRef"], "title": it["title"], "feedTitle": it["feedTitle"]}
            for it in r.json().get("items", [])
        ]


def tool_save_bookmark(target: str) -> dict:
    """Write tool — executes only after human approval (mock apply)."""
    return {"saved": True, "target": target}


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return PAGE


@app.post("/decide")
async def decide(req: Request) -> JSONResponse:
    body = await req.json()
    await decision_q.put(body["v"])
    return JSONResponse({"ok": True})


@app.get("/agent/stream")
async def agent_stream() -> StreamingResponse:
    async def gen():
        def emit(kind: str, text: str, **kw) -> str:
            return f"data: {json.dumps({'kind': kind, 'text': text, **kw}, ensure_ascii=False)}\n\n"

        # scripted mock-LLM trace (deterministic; no paid API)
        yield emit("assistant", "先检索 vLLM 相关文章。")
        hits = await tool_search("vLLM")
        for h in hits:
            yield emit("tool", f'search("vLLM") → [{h["feedTitle"]}] {h["title"]}  (cite: {h["entryRef"][:18]}…)')
        yield emit("assistant", f'找到 {len(hits)} 条,最高相关:「{hits[0]["title"]}」。写操作需要批准。')
        yield emit("approval", "save_bookmark → 工作区「AI 研究」")
        v = await asyncio.wait_for(decision_q.get(), timeout=120)
        if v == "approved":
            res = tool_save_bookmark("Quantization reduces memory usage at a small accuracy cost.")
            yield emit("tool", f"save_bookmark() → {json.dumps(res, ensure_ascii=False)}(批准后执行)")
            yield emit("assistant", "已保存。完成。", done=True)
        else:
            yield emit("assistant", "已取消保存。完成。", done=True)

    return StreamingResponse(gen(), media_type="text/event-stream")


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=18901, log_level="error")
