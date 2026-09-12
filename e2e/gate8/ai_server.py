"""OpenAI-compatible test server for Gate 8 E2E (local, no internet).

Implements just enough of the chat-completions contract to exercise the
Lumi agent: non-streamed + streamed (SSE) responses, one scripted tool
call round, deterministic tool-result continuation, and honest errors
on a bad model name. Scripted via the prompt content — no persistence.

    python3 ai_server.py --port 8321
    POST /v1/chat/completions   (OpenAI wire shape)
    GET  /healthz
"""

from __future__ import annotations

import argparse
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOOL_SPEC = {
    "type": "function",
    "function": {
        "name": "search",
        "description": "Keyword search over the RSS projection.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
}


def _content_of(messages: list[dict]) -> str:
    parts = []
    for message in messages:
        content = message.get("content")
        if isinstance(content, str):
            parts.append(content)
    return "\n".join(parts)


def _plan(messages: list[dict]) -> dict:
    """Script the reply from the conversation so far (deterministic)."""
    text = _content_of(messages)
    issued_tool_call = any(
        message.get("tool_calls") for message in messages if message.get("role") == "assistant"
    )
    tool_result_seen = any(message.get("role") == "tool" for message in messages)
    if not issued_tool_call and "请调用搜索" in text:
        return {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_e2e_1",
                    "type": "function",
                    "function": {
                        "name": "search",
                        "arguments": json.dumps({"query": "注意力"}, ensure_ascii=False),
                    },
                }
            ],
        }
    if tool_result_seen:
        return {
            "role": "assistant",
            "content": "搜索完成：已根据工具结果作答（E2E 受控回复）。",
        }
    return {"role": "assistant", "content": "你好，这是 E2E 受控回复。"}


def _chunks(reply: dict, tool_call_id: str):
    tool_calls = reply.get("tool_calls")
    if tool_calls:
        yield {"delta": {"role": "assistant", "content": None}}
        for index, call in enumerate(tool_calls):
            yield {
                "delta": {
                    "tool_calls": [
                        {
                            "index": index,
                            "id": call["id"],
                            "type": "function",
                            "function": {
                                "name": call["function"]["name"],
                                "arguments": call["function"]["arguments"],
                            },
                        }
                    ]
                }
            }
        yield {"delta": {}, "finish_reason": "tool_calls"}
        return
    text = reply.get("content") or ""
    for step in range(0, len(text), 4):
        yield {"delta": {"role": "assistant", "content": text[step : step + 4]}}
    yield {"delta": {}, "finish_reason": "stop"}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # noqa: A003 — quiet by default
        if args and len(args) > 1 and "%s" % args[0] != "GET /healthz":
            pass

    def do_GET(self):  # noqa: N802 — stdlib naming
        if self.path == "/healthz":
            body = json.dumps({"ok": True}).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self):  # noqa: N802 — stdlib naming
        if self.path != "/v1/chat/completions":
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("content-length") or 0)
        request = json.loads(self.rfile.read(length) or b"{}")
        if request.get("model") == "force-error":
            body = json.dumps({"error": {"message": "scripted failure", "type": "server_error"}}).encode()
            self.send_response(500)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        reply = _plan(request.get("messages") or [])
        created = int(time.time())
        if request.get("stream"):
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.end_headers()
            for index, piece in enumerate(_chunks(reply, "call_e2e_1")):
                event = {
                    "id": "chatcmpl-e2e",
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": request.get("model") or "e2e",
                    "choices": [{"index": 0, **piece}],
                }
                self.wfile.write(b"data: " + json.dumps(event, ensure_ascii=False).encode() + b"\n\n")
            self.wfile.write(b"data: [DONE]\n\n")
            return
        message = dict(reply)
        finish = "stop"
        if message.get("tool_calls"):
            finish = "tool_calls"
        body = json.dumps(
            {
                "id": "chatcmpl-e2e",
                "object": "chat.completion",
                "created": created,
                "model": request.get("model") or "e2e",
                "choices": [{"index": 0, "message": message, "finish_reason": finish}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
            ensure_ascii=False,
        ).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8321)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
