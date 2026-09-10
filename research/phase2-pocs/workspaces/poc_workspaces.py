#!/usr/bin/env python3
"""PoC 07-workspaces + 08-library-views: ItemRef workspace model and the
federated read-later/favorite/search view over RSS(FreshRSS ref) + Library.

Proves: workspaces store refs (never copies); a single SQL view federates
RSS entries (referenced, not duplicated) with native library items for
read-later / favorite / search screens.
Run: uv run python poc_workspaces.py
"""
from __future__ import annotations

import sqlite3
import time

SCHEMA = """
CREATE TABLE library_items (          -- Lumi-owned content ONLY (non-RSS)
  uuid TEXT PRIMARY KEY,
  kind TEXT NOT NULL CHECK (kind IN ('bookmark','clip','snapshot','api_item','newsletter_item','obsidian_note')),
  title TEXT NOT NULL,
  url TEXT,
  text_content TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE library_favorites (      -- Lumi-side favorite (RSS favorite stays in FreshRSS star)
  item_type TEXT NOT NULL CHECK (item_type IN ('rss','library')),
  rss_item_ref TEXT,                  -- rss:<opaque-entry-ref> (no copy)
  library_uuid TEXT REFERENCES library_items(uuid),
  created_at TEXT NOT NULL,
  CHECK ((item_type='rss') != (item_type='library'))
);
CREATE TABLE workspace_items (
  workspace_id TEXT NOT NULL,
  item_type TEXT NOT NULL CHECK (item_type IN ('rss','library')),
  rss_item_ref TEXT,                  -- typed refs only — never object copies
  library_uuid TEXT,
  position INTEGER NOT NULL DEFAULT 0,
  added_at TEXT NOT NULL,
  CHECK ((item_type='rss') != (item_type='library'))
);
CREATE VIRTUAL TABLE search_fts USING fts5(
  ref, kind, title, body, tokenize='unicode61'
);
"""

FEEDS = [
    # (ref, kind, title, body, read_later, favorite)  -- rss rows mirror refs to FreshRSS entries only
    ("rss:fr:e1001", "rss", "vLLM V1 release notes", "PagedAttention v1 engine release ...", 1, 1),
    ("rss:fr:e1002", "rss", "The Verge: Muse AI", "Meta's music model creepiness ...", 1, 0),
    ("rss:fr:e1003", "rss", "OpenAI dev day recap", "devday announcements summary ...", 0, 0),
]
LIBS = [
    ("lib:0001", "bookmark", "Bergamot model registry", "33 bergamot models, no chinese pair", 1, 1),
    ("lib:0002", "clip", "Local translation notes", "chrome translator kit component gap", 1, 0),
]


def main() -> None:
    t0 = time.perf_counter()
    db = sqlite3.connect(":memory:")
    db.executescript(SCHEMA)
    for ref, kind, title, body, read_later, fav in FEEDS:
        db.execute("INSERT INTO search_fts VALUES (?,?,?,?)", (ref, kind, title, body))
        if read_later:
            db.execute("INSERT INTO workspace_items VALUES ('ws-read-later','rss',?,NULL,0,'2026-09-10')", (ref,))
        if fav:
            db.execute("INSERT INTO library_favorites VALUES ('rss',?,NULL,'2026-09-10')", (ref,))
    for uuid, kind, title, body, read_later, fav in LIBS:
        db.execute("INSERT INTO library_items VALUES (?,?,?,?,?,?)", (uuid, kind, title, body, None, "2026-09-10"))
        db.execute("INSERT INTO search_fts VALUES (?,?,?,?)", (uuid, kind, title, body))
        if read_later:
            db.execute("INSERT INTO workspace_items VALUES ('ws-read-later','library',NULL,?,0,'2026-09-10')", (uuid,))
        if fav:
            db.execute("INSERT INTO library_favorites VALUES ('library',NULL,?,'2026-09-10')", (uuid,))

    # 08-library-views: federated views over BOTH domains without copying RSS data
    db.executescript("""
    CREATE VIEW v_favorites AS
      SELECT 'rss' AS domain, f.rss_item_ref AS ref
        FROM library_favorites f WHERE f.item_type='rss'
      UNION ALL
      SELECT 'library', f.library_uuid FROM library_favorites f WHERE f.item_type='library';
    CREATE VIEW v_read_later AS
      SELECT w.item_type AS domain, COALESCE(w.rss_item_ref, w.library_uuid) AS ref,
             COALESCE(li.title, '') AS title
        FROM workspace_items w LEFT JOIN library_items li ON li.uuid = w.library_uuid
       WHERE w.workspace_id='ws-read-later';
    """)
    print("federated favorites:", db.execute("SELECT * FROM v_favorites ORDER BY 1").fetchall())
    print("read-later queue:   ", db.execute("SELECT domain, ref, title FROM v_read_later ORDER BY ref").fetchall())

    # unified search: FTS across both domains, ref resolves at render time
    q = "SELECT ref, kind, title, bm25(search_fts) AS rank FROM search_fts WHERE search_fts MATCH ? ORDER BY rank"
    for term in ("translation", "vllm"):
        rows = db.execute(q, (term,)).fetchall()
        print(f"search '{term}':", [(r[0], r[2][:28]) for r in rows])

    # workspace membership never copies: rss rows must carry ONLY a ref
    # (structural: the table has no content column; uuid must be NULL for rss)
    bad = db.execute(
        "SELECT COUNT(*) FROM workspace_items WHERE item_type='rss' AND (rss_item_ref IS NULL OR library_uuid IS NOT NULL)"
    ).fetchone()[0]
    print("workspace rss rows violating ref-only shape (must be 0):", bad)
    print(f"OK in {time.perf_counter()-t0:.3f}s")


if __name__ == "__main__":
    main()
