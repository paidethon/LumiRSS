#!/usr/bin/env python3
"""Probe URL variants for candidates that failed round 1 (fixed data).

Usage:
    uv run --with feedparser --with httpx python probe_variants.py
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import feedparser
import httpx

UA = "LumiRSS-FeedValidator/1.0 (+https://github.com/paidethon/LumiRSS)"
HERE = Path(__file__).resolve().parent

VARIANTS: dict[str, list[str]] = {
    "Apple ML Research": [
        "https://machinelearning.apple.com/rss.xml",
        "https://machinelearning.apple.com/feed.xml",
        "https://machinelearning.apple.com/atom.xml",
    ],
    "BAIR Blog": [
        "https://bair.berkeley.edu/blog/feed.xml",
        "https://bair.berkeley.edu/feed.xml",
        "http://bair.berkeley.edu/blog/feed.xml",
    ],
    "Meta AI Blog": [
        "https://ai.meta.com/blog/feed/",
        "https://ai.meta.com/blog/rss/",
        "https://about.fb.com/news/category/ai/feed/",
    ],
    "Mistral AI News": [
        "https://mistral.ai/feed.xml",
        "https://mistral.ai/rss.xml",
        "https://news.mistral.ai/feed.xml",
    ],
    "Cohere Blog": [
        "https://cohere.com/blog/atom.xml",
        "https://cohere.com/blog/rss.xml",
        "https://txt.cohere.com/rss/",
        "https://cohere.com/rss.xml",
    ],
    "Allen Institute for AI": [
        "https://allenai.org/blog/feed",
        "https://allenai.org/feed.xml",
        "https://allenai.org/blog/rss.xml",
    ],
    "Anthropic News": [
        "https://www.anthropic.com/rss.xml",
        "https://www.anthropic.com/news/rss.xml",
        "https://www.anthropic.com/rss/news.xml",
        "https://rsshub.app/anthropic/news",
    ],
    "EleutherAI Blog": [
        "https://www.eleuther.ai/rss.xml",
        "https://www.eleuther.ai/feed.xml",
        "https://blog.eleuther.ai/atom.xml",
    ],
    "Weights & Biases Blog": [
        "https://wandb.ai/rss.xml",
        "https://www.wandb.craft/feed",
        "https://wandb.ai/feed",
    ],
    "Together AI Blog": [
        "https://www.together.ai/blog/rss.xml",
        "https://www.together.ai/rss.xml",
        "https://www.together.ai/feed",
    ],
    "Modal Blog": [
        "https://modal.blog/feed.xml",
        "https://modal.com/feed.xml",
        "https://modal.blog/rss.xml",
    ],
    "Replicate Blog": [
        "https://replicate.com/blog/feed.xml",
        "https://blog.replicate.com/feed.xml",
        "https://replicate.com/rss.xml",
    ],
    "Groq Blog": [
        "https://groq.com/rss.xml",
        "https://groq.com/blog/feed/",
        "https://groq.com/feed/",
    ],
    "vLLM Blog": [
        "https://blog.vllm.ai/index.xml",
        "https://blog.vllm.ai/atom.xml",
        "https://blog.vllm.ai/rss.xml",
    ],
    "LlamaIndex Blog": [
        "https://www.llamaindex.ai/blog/rss.xml",
        "https://www.llamaindex.ai/rss.xml",
        "https://www.llamaindex.ai/feed",
    ],
    "LangChain Blog": [
        "https://blog.langchain.com/feed/",
        "https://blog.langchain.dev/feed/",
        "https://blog.langchain.com/rss/",
    ],
    "Arize AI Blog": [
        "https://arize.com/blog/feed/",
        "https://arize.com/feed/",
        "https://arize.com/rss.xml",
    ],
    "Evidently AI Blog": [
        "https://www.evidentlyai.com/rss.xml",
        "https://www.evidentlyai.com/feed",
        "https://www.evidentlyai.com/blog/rss",
    ],
    "Lightning AI": [
        "https://lightning.ai/feed/",
        "https://lightning.ai/blog/feed.xml",
        "https://lightning.ai/rss.xml",
    ],
    "Hamel Husain": [
        "https://hamel.dev/index.xml",
        "https://hamel.dev/atom.xml",
        "https://hamel.dev/feed",
    ],
    "Jeremy Howard / fast.ai": [
        "https://www.fast.ai/feed.xml",
        "https://www.fast.ai/posts/feed.rss",
        "https://jeremyjhoward.wordpress.com/feed/",
    ],
    "Vicki Boykis": [
        "https://vickiboykis.com/atom.xml",
        "https://vickiboykis.com/index.xml",
        "https://vickiboykis.com/rss.xml",
    ],
    "Import AI": [
        "https://importai.substack.com/feed/",
        "https://www.jack-clark.net/feed/",
        "https://importai.co/feed/",
    ],
    "The Batch": [
        "https://www.deeplearning.ai/the-batch/feed/",
        "https://www.deeplearning.ai/the-batch/rss/",
        "https://www.deeplearning.ai/feed/the-batch/",
    ],
    "MarkTechPost": [
        "https://www.marktechpost.com/feed/",
        "https://www.marktechpost.com/feed",
        "https://marktechpost.com/feed/",
    ],
    # extra candidates to fill composition gaps
    "TLDR AI Newsletter": [
        "https://tldr.tech/ai/rss",
        "https://tldr.tech/ai/feed",
    ],
    "AI News (Hugging Face daily)": [
        "https://huggingface.co/papers/feed",
    ],
    "MIT AI News (Simon extra)": [
        "https://www.technologyreview.com/feed/",
    ],
    "Chip Huyen newsletter": [
        "https://huyenchip.com/feed/",
    ],
    "Kaggle Blog": [
        "https://blog.kaggle.com/feed/",
    ],
    "DeepLearning.AI Blog": [
        "https://www.deeplearning.ai/blog/feed/",
    ],
}


def main() -> None:
    results = []
    with httpx.Client(
        follow_redirects=True,
        timeout=httpx.Timeout(25.0, connect=10.0),
        headers={
            "User-Agent": UA,
            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
        },
    ) as client:
        for name, urls in VARIANTS.items():
            best = None
            for url in urls:
                rec = {"name": name, "url": url}
                t0 = time.perf_counter()
                try:
                    resp = client.get(url)
                    rec.update(status=resp.status_code, finalUrl=str(resp.url),
                               contentType=resp.headers.get("content-type", "").split(";")[0],
                               latencyS=round(time.perf_counter() - t0, 2))
                    if resp.status_code == 200:
                        feed = feedparser.parse(resp.content)
                        if feed.entries:
                            rec.update(feedType=feed.get("version", ""),
                                       feedTitle=feed.feed.get("title", "")[:80],
                                       itemCount=len(feed.entries),
                                       verdict="PASS")
                            best = rec
                            break
                        rec["verdict"] = "NO_ENTRIES"
                except Exception as exc:  # noqa: BLE001
                    rec["verdict"] = "EXC"
                    rec["error"] = f"{type(exc).__name__}: {exc}"[:120]
                if "verdict" not in rec:
                    rec["verdict"] = f"HTTP_{resp.status_code}"
                print(f"  {rec['verdict']:10s} {rec.get('status', '-'):>3} {url}"
                      + (f" | {rec.get('error', '')}" if rec.get("error") else ""))
            if best:
                print(f"=> {name}: {best['url']} ({best.get('feedType')}, {best.get('itemCount')} items)")
                results.append(best)
    (HERE / "probe-results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n{len(results)}/{len(VARIANTS)} publishers resolved")


if __name__ == "__main__":
    main()
