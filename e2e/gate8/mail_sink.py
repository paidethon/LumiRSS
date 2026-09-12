"""Minimal local SMTP sink + HTTP inspector for the Gate 8 E2E stack.

Stands in for Mailpit when the local docker proxy cannot pull images:
- SMTP listener on :1025 stores every message (bounded);
- HTTP API on :8025 serves GET /api/v1/messages (JSON, newest first)
  so the smoke script can assert delivery and non-empty bodies.

    python3 mail_sink.py
"""

from __future__ import annotations

import asyncio
import json
import threading
from email import message_from_bytes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_MESSAGES: list[dict] = []
_LOCK = threading.Lock()
_MAX_MESSAGES = 200


class _Sink(asyncio.Protocol):
    def connection_made(self, transport) -> None:  # noqa: ANN001
        self._transport = transport
        self._buffer = b""
        self._data_mode = False
        self._peer: str = ""
        transport.write(b"220 lumirss-e2e-sink ready\r\n")

    def data_received(self, data: bytes) -> None:  # noqa: ANN001
        self._buffer += data
        while b"\r\n" in self._buffer:
            line, self._buffer = self._buffer.split(b"\r\n", 1)
            self._handle_line(line)

    def _handle_line(self, line: bytes) -> None:
        upper = line.upper()
        if self._data_mode:
            if line == b".":
                self._data_mode = False
                self._store()
                self._transport.write(b"250 accepted\r\n")
            else:
                self._body += line + b"\r\n"
            return
        if upper.startswith(b"EHLO") or upper.startswith(b"HELO"):
            self._peer = line[4:].decode("latin-1", errors="replace").strip()
            self._transport.write(
                b"250-lumirss-e2e-sink\r\n250-8BITMIME\r\n250 OK\r\n"
            )
        elif upper.startswith(b"MAIL FROM"):
            self._mail_from = line.split(b":", 1)[1].decode("latin-1").strip()
            self._transport.write(b"250 ok\r\n")
        elif upper.startswith(b"RCPT TO"):
            self._rcpts.append(line.split(b":", 1)[1].decode("latin-1").strip())
            self._transport.write(b"250 ok\r\n")
        elif upper == b"DATA":
            self._data_mode = True
            self._body = b""
            self._transport.write(b"354 end with .\r\n")
        elif upper == b"RSET":
            self._reset()
            self._transport.write(b"250 ok\r\n")
        elif upper == b"NOOP":
            self._transport.write(b"250 ok\r\n")
        elif upper == b"QUIT":
            self._transport.write(b"221 bye\r\n")
            self._transport.close()
        else:
            self._transport.write(b"250 ok\r\n")

    def _reset(self) -> None:
        self._rcpts = []
        self._mail_from = ""
        self._body = b""
        self._data_mode = False

    def _store(self) -> None:
        try:
            parsed = message_from_bytes(self._body)
            subject = str(parsed.get("Subject", ""))
            text = ""
            if parsed.is_multipart():
                for part in parsed.walk():
                    if part.get_content_type() == "text/plain":
                        text = part.get_payload(decode=True).decode(
                            "utf-8", errors="replace"
                        )
                        break
            else:
                text = (parsed.get_payload(decode=True) or b"").decode(
                    "utf-8", errors="replace"
                )
            with _LOCK:
                _MESSAGES.append(
                    {
                        "From": self._mail_from,
                        "To": ", ".join(self._rcpts),
                        "Subject": subject,
                        "Text": text,
                        "BodyHTML": "",
                    }
                )
                del _MESSAGES[:-_MAX_MESSAGES]
        except Exception:  # noqa: BLE001 — the sink never crashes on mail
            pass
        self._reset()

    # per-connection state (created lazily before any use)
    @property
    def _rcpts(self) -> list:  # noqa: ANN201
        if not hasattr(self, "_rcpts_list"):
            self._rcpts_list = []
        return self._rcpts_list

    @_rcpts.setter
    def _rcpts(self, value: list) -> None:
        self._rcpts_list = value

    @property
    def _mail_from(self) -> str:
        return getattr(self, "_mail_from_value", "")

    @_mail_from.setter
    def _mail_from(self, value: str) -> None:
        self._mail_from_value = value

    @property
    def _body(self) -> bytes:
        return getattr(self, "_body_value", b"")

    @_body.setter
    def _body(self, value: bytes) -> None:
        self._body_value = value


class _Api(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # noqa: A003 — quiet
        pass

    def do_GET(self):  # noqa: N802 — stdlib naming
        if self.path.startswith("/api/v1/messages"):
            with _LOCK:
                body = json.dumps(
                    {"total": len(_MESSAGES), "messages": list(reversed(_MESSAGES))}
                ).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()


def main() -> None:
    loop = asyncio.new_event_loop()
    threading.Thread(
        target=lambda: loop.run_until_complete(_smtp()), daemon=True
    ).start()
    ThreadingHTTPServer(("0.0.0.0", 8025), _Api).serve_forever()


async def _smtp() -> None:
    loop = asyncio.get_running_loop()
    server = loop.create_server(_Sink, "0.0.0.0", 1025)
    await server
    await asyncio.Event().wait()


if __name__ == "__main__":
    main()
