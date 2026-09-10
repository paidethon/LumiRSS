#!/usr/bin/env python3
"""PoC 04-email-newsletters: local SMTP in -> parse -> Atom out -> FreshRSS-
importable feed; plus outbound digest rendered to a local SMTP sink (no real
mail ever leaves localhost).

Run: uv run --with aiosmtpd python poc_newsletters.py
"""
from __future__ import annotations

import asyncio
import email
import email.policy
import time
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

from aiosmtpd.controller import Controller as SmtpController
from aiosmtpd.handlers import Message as MessageHandler

HERE = Path(__file__).resolve().parent
RECEIVED: list[email.message.EmailMessage] = []


class Sink(MessageHandler):
    """Collect messages instead of writing to disk."""

    def handle_message(self, message) -> None:  # type: ignore[override]
        RECEIVED.append(message)


def render_atom(items: list[dict], feed_url: str) -> str:
    """Kill-the-Newsletter! pattern: each mail becomes one Atom entry."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    entries = []
    for it in items:
        entries.append(
            f"""  <entry>
    <id>urn:mail:{it['id']}</id>
    <title>{it['subject']}</title>
    <author><name>{it['from']}</name></author>
    <updated>{it['date']}</updated>
    <link href="{feed_url}#{it['id']}"/>
    <content type="html">{it['html'][:400]}</content>
  </entry>"""
        )
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<feed xmlns="http://www.w3.org/2005/Atom">\n'
        f"  <title>Newsletter Bridge</title>\n  <updated>{now}</updated>\n"
        f'  <id>{feed_url}</id>\n' + "\n".join(entries) + "\n</feed>\n"
    )


async def main() -> None:
    t0 = time.perf_counter()
    controller = SmtpController(Sink(), hostname="127.0.0.1", port=18025)
    controller.start()
    try:
        # --- inbound: two fake newsletter mails over local SMTP ---
        for i, subj in enumerate(["Weekly AI Digest #42", "Deep dive: state-space models"]):
            msg = EmailMessage()
            msg["From"] = "digest@newsletters.example"
            msg["To"] = "lumi-bridge@127.0.0.1"
            msg["Subject"] = subj
            msg["Date"] = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S %z")
            msg.set_content(f"plain fallback for {subj}")
            msg.add_alternative(f"<html><body><h1>{subj}</h1><p>Article body #{i} …</p></body></html>", subtype="html")
            import smtplib
            with smtplib.SMTP("127.0.0.1", 18025) as smtp:
                smtp.send_message(msg)
        # small yield for the handler thread
        for _ in range(50):
            if len(RECEIVED) >= 2:
                break
            await asyncio.sleep(0.05)
        print(f"SMTP received: {len(RECEIVED)} mails")

        # --- bridge: mail -> Atom ---
        items = []
        for i, raw in enumerate(RECEIVED):
            m = email.message_from_bytes(raw.as_bytes(), policy=email.policy.default)
            html_part = m.get_body(("html", "plain"))
            items.append({
                "id": f"m{i}",
                "subject": m["Subject"],
                "from": m["From"],
                "date": m["Date"],
                "html": html_part.get_content().replace("&", "&amp;").replace("<", "&lt;") if html_part else "",
            })
        atom = render_atom(items, "http://127.0.0.1:8080/feeds/newsletters.atom")
        out = HERE / "newsletters.atom"
        out.write_text(atom, encoding="utf-8")
        ok = all(x in atom for x in ("<feed", "<entry>", "Weekly AI Digest #42", "state-space"))
        print(f"Atom feed written ({len(atom)} bytes, entries={atom.count('<entry>')}, valid-shape={ok})")

        # --- outbound digest -> local sink (never a real mailbox) ---
        digest = EmailMessage()
        digest["From"] = "lumi@127.0.0.1"
        digest["To"] = "reader@127.0.0.1"
        digest["Subject"] = "LumiRSS daily digest — 2 items"
        digest.set_content("1) vLLM V1  2) Muse AI")
        digest.add_alternative(
            "<html><body><h1>LumiRSS Daily</h1><ul><li>vLLM V1</li><li>Muse AI</li></ul></body></html>",
            subtype="html",
        )
        before = len(RECEIVED)
        import smtplib as sm2
        with sm2.SMTP("127.0.0.1", 18025) as smtp:
            smtp.send_message(digest)
        for _ in range(50):
            if len(RECEIVED) > before:
                break
            await asyncio.sleep(0.05)
        got = email.message_from_bytes(RECEIVED[-1].as_bytes(), policy=email.policy.default)
        both = bool(got.get_body("plain")) and bool(got.get_body("html"))
        print(f"outbound digest received by sink: subject={got['Subject']!r} html+text={both}")
    finally:
        controller.stop()
    print(f"OK in {time.perf_counter()-t0:.2f}s")


if __name__ == "__main__":
    asyncio.run(main())
