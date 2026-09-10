#!/usr/bin/env python3
"""Round 3: verify web-search-resolved feed URLs (fixed data)."""
from __future__ import annotations

import json
import time
from pathlib import Path

import feedparser
import httpx

UA = "LumiRSS-FeedValidator/1.0 (+https://github.com/paidethon/LumiRSS)"
HERE = Path(__file__).resolve().parent

CANDIDATES: list[dict] = [
    {"name": "vLLM Blog", "url": "https://vllm.ai/blog/rss.xml", "category": "engineering"},
    {"name": "vLLM Blog (alt)", "url": "https://blog.vllm.ai/feed.xml", "category": "engineering"},
    {"name": "LangChain Blog", "url": "https://www.langchain.com/blog/rss.xml", "category": "engineering"},
    {"name": "LangChain Blog (alt2)", "url": "https://blog.langchain.com/rss/", "category": "engineering"},
    {"name": "LlamaIndex Blog", "url": "https://www.llamaindex.ai/blog/rss", "category": "engineering"},
    {"name": "LlamaIndex Blog (alt)", "url": "https://www.llamaindex.ai/rss", "category": "engineering"},
    {"name": "Modal Blog", "url": "https://modal.blog/feed", "category": "engineering"},
    {"name": "Modal Blog (alt)", "url": "https://modal.com/blog/rss.xml", "category": "engineering"},
    {"name": "W&B Blog", "url": "https://wandb.ai/fully-connected/rss.xml", "category": "engineering"},
    {"name": "W&B Blog (alt)", "url": "https://www.wandb.ai/feed.xml", "category": "engineering"},
    {"name": "Replicate Blog", "url": "https://blog.replicate.com/feed/", "category": "engineering"},
    {"name": "Evidently AI", "url": "https://www.evidentlyai.com/blog/rss.xml", "category": "engineering"},
    {"name": "The Batch", "url": "https://www.deeplearning.ai/feed/the-batch/", "category": "newsletters"},
    {"name": "The Batch (alt)", "url": "https://deeplearning.ai/the-batch/feed/", "category": "newsletters"},
    {"name": "TLDR AI", "url": "https://tldr.tech/ai/feed.xml", "category": "newsletters"},
    {"name": "TLDR AI (alt)", "url": "https://tldr.tech/ai/rss.xml", "category": "newsletters"},
    {"name": "BAIR Blog", "url": "https://bair.berkeley.edu/blog/feed.xml", "category": "labs"},
    {"name": "AI2 Blog", "url": "https://allenai.org/blog/rss", "category": "labs"},
    {"name": "AI2 Blog (alt)", "url": "https://allenai.org/blog/feed", "category": "labs"},
    {"name": "Cohere Blog", "url": "https://cohere.com/blog/rss", "category": "labs"},
    {"name": "Groq Blog", "url": "https://groq.com/blog/rss", "category": "engineering"},
    {"name": "Chip Huyen blog", "url": "https://huyenchip.com/feed.xml", "category": "experts"},
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
                        rec.update(feedType=feed.get("version", ""),
                                   feedTitle=feed.feed.get("title", "")[:80],
                                   itemCount=len(feed.entries),
                                   latest=time.strftime("%Y-%m-%d", time.gmtime(max(
                                       time.mktime(e.get("published_parsed") or e.get("updated_parsed") or (0, 0, 0, 0, 0, 0, 0, 0, 0))
                                       for e in feed.entries))),
                                   verdict="PASS")
                    else:
                        rec["verdict"] = "NO_ENTRIES"
                else:
                    rec["verdict"] = f"HTTP_{resp.status_code}"
            except Exception as exc:  # noqa: BLE001
                rec["verdict"] = "EXC"
                rec["error"] = f"{type(exc).__name__}: {exc}"[:120]
            print(f"{rec['verdict']:11s} {rec['name']:26s} {rec['url']}")
            out.append(rec)
    (HERE / "probe-results-round3.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("done")


if __name__ == "__main__":
    main()
