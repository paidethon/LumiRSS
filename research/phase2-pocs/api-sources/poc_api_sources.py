#!/usr/bin/env python3
"""PoC 03-api-sources: generic JSON API -> unified item via JMESPath.

Three real public APIs (GitHub releases, HN Algolia, arXiv-style nested
listing via HN), each mapped with a stored JMESPath expression — proving the
"declarative mapping, no custom DSL" architecture.
Run: uv run --with jmespath --with httpx python poc_api_sources.py
"""
from __future__ import annotations

import json
import time

import httpx
import jmespath

SOURCES = [
    {
        "name": "GitHub releases (FastAPI)",
        "endpoint": "https://api.github.com/repos/fastapi/fastapi/releases?per_page=5",
        "items_expr": "[].{id: id, title: name, url: html_url, published: published_at, author: author.login}",
        "title_expr": "tag_name",
    },
    {
        "name": "Hacker News front page (Algolia)",
        "endpoint": "https://hn.algolia.com/api/v1/search_by_date?query=fastapi&tags=story&hitsPerPage=5",
        "items_expr": "hits[].{id: objectID, title: title, url: url, published: created_at, author: author}",
        "title_expr": "story_title",
    },
    {
        "name": "Open Library search (deeply nested JSON)",
        "endpoint": "https://openlibrary.org/search.json?q=machine+learning&limit=3&fields=title,author_name,first_publish_year,key",
        "items_expr": "docs[].{id: key, title: title, published: to_string(first_publish_year), author: join(', ', author_name || `[]`)}",
        "title_expr": "title",
    },
]


def main() -> None:
    t0 = time.perf_counter()
    with httpx.Client(timeout=25, headers={"User-Agent": "LumiRSS-PoC/1.0", "Accept": "application/json"}) as c:
        for src in SOURCES:
            r = c.get(src["endpoint"])
            r.raise_for_status()
            items = jmespath.search(src["items_expr"], r.json())
            print(f"\n== {src['name']}  (HTTP {r.status_code}, {len(items)} items)")
            for it in items[:3]:
                print(f"   {str(it.get('published'))[:10]}  {str(it.get('title'))[:60]}  ->  {str(it.get('url') or it.get('id'))[:60]}")
    print(f"\nJMESPath mapping of 3 public APIs OK in {time.perf_counter()-t0:.1f}s")


if __name__ == "__main__":
    main()
