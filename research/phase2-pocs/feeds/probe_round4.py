#!/usr/bin/env python3
"""Round 4: engineering + newsletter gap fillers (fixed data)."""
from __future__ import annotations

import json
import time
from pathlib import Path

import feedparser
import httpx

UA = "LumiRSS-FeedValidator/1.0 (+https://github.com/paidethon/LumiRSS)"
HERE = Path(__file__).resolve().parent

CANDIDATES: list[dict] = [
    {"name": "PyTorch Blog", "url": "https://pytorch.org/blog/feed.xml", "category": "engineering"},
    {"name": "TensorFlow Blog", "url": "https://blog.tensorflow.org/feeds/posts.xml", "category": "engineering"},
    {"name": "Weaviate Blog", "url": "https://weaviate.io/blog/rss.xml", "category": "engineering"},
    {"name": "Weaviate Blog (alt)", "url": "https://weaviate.io/blog/feed.xml", "category": "engineering"},
    {"name": "Qdrant Blog", "url": "https://qdrant.tech/rss/", "category": "engineering"},
    {"name": "Qdrant Blog (alt)", "url": "https://qdrant.tech/articles/rss/", "category": "engineering"},
    {"name": "GitHub AI Blog", "url": "https://github.blog/category/ai/feed/", "category": "engineering"},
    {"name": "Jina AI Blog", "url": "https://jina.ai/blog/feed.xml", "category": "engineering"},
    {"name": "LlamaIndex Blog", "url": "https://www.llamaindex.ai/blog/feed", "category": "engineering"},
    {"name": "Data Elixir", "url": "https://dataelixir.com/feed/", "category": "newsletters"},
    {"name": "Towards AI", "url": "https://pub.towardsai.net/feed", "category": "newsletters"},
    {"name": "Ben's Bites", "url": "https://www.bensbites.com/rss.xml", "category": "newsletters"},
    {"name": "Ben's Bites (alt)", "url": "https://bensbites.beehiiv.com/feed", "category": "newsletters"},
    {"name": "The Rundown AI", "url": "https://www.therundown.ai/feed", "category": "newsletters"},
    {"name": "RunLLM/other", "url": "https://newsletter.maartengrootendorst.nl/feed", "category": "newsletters"},
]


def main() -> None:
    out = []
    with httpx.Client(
        follow_redirects=True,
        timeout=httpx.Timeout(40.0, connect=20.0),
        headers={
            "User-Agent": UA,
            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
        },
    ) as client:
        for cand in CANDIDATES:
            rec = {"name": cand["name"], "url": cand["url"], "category": cand["category"]}
            t0 = time.perf_counter()
            try:
                resp = client.get(cand["url"])
                rec.update(status=resp.status_code,
                           finalUrl=str(resp.url),
                           contentType=resp.headers.get("content-type", "").split(";")[0],
                           latencyS=round(time.perf_counter() - t0, 2))
                if resp.status_code == 200:
                    feed = feedparser.parse(resp.content)
                    if feed.entries:
                        latest = 0
                        for e in feed.entries:
                            t = e.get("published_parsed") or e.get("updated_parsed")
                            if t:
                                latest = max(latest, time.mktime(t))
                        rec.update(feedType=feed.get("version", ""),
                                   feedTitle=feed.feed.get("title", "")[:80],
                                   itemCount=len(feed.entries),
                                   latest=time.strftime("%Y-%m-%d", time.gmtime(latest)) if latest else None,
                                   verdict="PASS")
                    else:
                        rec["verdict"] = "NO_ENTRIES"
                else:
                    rec["verdict"] = f"HTTP_{resp.status_code}"
            except Exception as exc:  # noqa: BLE001
                rec["verdict"] = "EXC"
                rec["error"] = f"{type(exc).__name__}: {exc}"[:120]
            print(f"{rec['verdict']:11s} {rec.get('itemCount', '-'):>4} items  latest={rec.get('latest', '-')}  {rec['name']:24s} {rec['url']}")
            out.append(rec)
    (HERE / "probe-results-round4.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("done")


if __name__ == "__main__":
    main()
