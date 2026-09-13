"""Journey E2E (in-process): external push -> inbox -> workbench -> search.

Executes the second overnight success loop end to end against the real
FastAPI app + real Lumi SQLite (temp file), no mocks:

  1. operator creates an inbox connector (bearer secret shown once)
  2. external script POSTs JSON (with malicious HTML) to the ingest URL
  3. replaying the same guid converges (idempotent, no duplicate)
  4. the workbench lists the item ref and resolves it to a unified card
  5. unified search finds the pushed content (library leg)
  6. the item can be attached to the read-later workspace (cross-device state)
  7. GET /api/v1/sources lists the connector in the unified registry
"""

import asyncio
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from lumirss.main import app
from lumirss.storage import Database


def run() -> None:
    with TestClient(app) as client, tempfile.TemporaryDirectory() as tmp:
        app.state.db = Database(str(Path(tmp) / "lumi.sqlite"))

        # 1. create connector
        created = client.post(
            "/api/v1/inbox/sources", json={"name": "night-script"}
        ).json()
        assert created["secret"], "secret must be returned exactly once"
        ingest_url = created["ingestPath"]
        print(f"[1] connector created: {created['uuid']} ingest={ingest_url}")

        headers = {"Authorization": f"Bearer {created['secret']}"}

        # 2. push an item with hostile HTML
        push = {
            "guid": "nightly-report-2026-09-13",
            "title": "夜间采集报告",
            "url": "https://example.com/report",
            "contentHtml": "<p>SQLite 迁移完成</p><script>alert(1)</script>",
            "publishedAt": "2026-09-13T18:30:00+00:00",
            "categories": ["ops"],
        }
        resp = client.post(ingest_url, json=push, headers=headers)
        assert resp.status_code == 200, resp.text
        ref = resp.json()["ref"]
        assert resp.json()["status"] == "created"
        print(f"[2] pushed -> {ref} (hostile HTML stripped server-side)")

        # 3. replay is idempotent
        resp = client.post(ingest_url, json=push, headers=headers)
        assert resp.json()["status"] == "exists"
        items = client.get("/api/v1/inbox/items").json()
        assert len(items["items"]) == 1
        print("[3] replay converged: status=exists, 1 row total")

        # 4. workbench resolves the ref to a unified card
        card = client.post("/api/v1/resolve", json={"refs": [ref]}).json()["items"][0]
        assert card["kind"] == "api_item"
        assert card["source"] == "Inbox · night-script"
        assert "script" not in (card["excerpt"] or "")
        print(f"[4] resolved card: kind={card['kind']} title={card['title']}")

        # 5. unified search finds the pushed content
        hits = client.get("/api/v1/search", params={"q": "SQLite 迁移"}).json()
        lib = hits.get("library") or []
        assert any(hit["ref"] == ref for hit in lib), hits
        print(f"[5] unified search hit: {[h['title'] for h in lib]}")

        # 6. read-later attach (server-side cross-device state)
        resp = client.post(
            "/api/v1/workspaces/read-later/items",
            json={"itemRef": ref},
        )
        assert resp.status_code in (200, 201), resp.text
        timeline = client.get(
            "/api/v1/workspaces/read-later/timeline"
        ).json()
        assert any(row["itemRef"] == ref for row in timeline["items"]), timeline
        print("[6] attached to read-later; server timeline shows it")

        # 7. unified source registry
        sources = client.get("/api/v1/sources").json()["sources"]
        inbox_rows = [s for s in sources if s["type"] == "inbox"]
        assert len(inbox_rows) == 1 and inbox_rows[0]["label"] == "night-script"
        types = sorted({s["type"] for s in sources})
        print(f"[7] registry rows: types={types}")

        # cleanup: delete connector cascades everything
        client.delete(f"/api/v1/inbox/sources/{created['uuid']}")
        leftovers = client.get("/api/v1/inbox/items").json()
        assert leftovers["items"] == []
        print("[8] connector deleted; items + projections cascaded")

    print("\nJOURNEY PASS: webhook -> inbox -> workbench -> search -> read-later")


if __name__ == "__main__":
    asyncio.run(asyncio.to_thread(run))
