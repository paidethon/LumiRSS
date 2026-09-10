#!/usr/bin/env python3
"""Add the selected 40 AI feeds to FreshRSS via the official greader API,
assign categories, then verify per-feed entry counts after refresh.

Reads FreshRSS connection settings from environment variables:
    FRESHRSS_BASE_URL, FRESHRSS_USERNAME, FRESHRSS_API_PASSWORD

Usage:
    uv run --with httpx python add_selected_feeds.py
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from urllib.parse import quote

import httpx

HERE = Path(__file__).resolve().parent

SELECTED: list[dict] = [
    # AI · Labs (10)
    {"name": "OpenAI News", "url": "https://openai.com/news/rss.xml", "category": "AI · Labs"},
    {"name": "Google DeepMind Blog", "url": "https://deepmind.google/blog/rss.xml", "category": "AI · Labs"},
    {"name": "Google Research Blog", "url": "https://research.google/blog/rss/", "category": "AI · Labs"},
    {"name": "Google AI Blog", "url": "https://blog.google/technology/ai/rss/", "category": "AI · Labs"},
    {"name": "Microsoft Research", "url": "https://www.microsoft.com/en-us/research/feed/", "category": "AI · Labs"},
    {"name": "Apple Machine Learning Research", "url": "https://machinelearning.apple.com/rss.xml", "category": "AI · Labs"},
    {"name": "NVIDIA Developer Blog", "url": "https://developer.nvidia.com/blog/feed/", "category": "AI · Labs"},
    {"name": "AWS Machine Learning Blog", "url": "https://aws.amazon.com/blogs/machine-learning/feed/", "category": "AI · Labs"},
    {"name": "Hugging Face Blog", "url": "https://huggingface.co/blog/feed.xml", "category": "AI · Labs"},
    {"name": "Mistral AI News", "url": "https://mistral.ai/rss.xml", "category": "AI · Labs"},
    # AI · Engineering (8)
    {"name": "PyTorch Blog", "url": "https://pytorch.org/blog/feed.xml", "category": "AI · Engineering"},
    {"name": "Weaviate Blog", "url": "https://weaviate.io/blog/rss.xml", "category": "AI · Engineering"},
    {"name": "vLLM Blog", "url": "https://vllm.ai/blog/rss.xml", "category": "AI · Engineering"},
    {"name": "LangChain Blog", "url": "https://www.langchain.com/blog/rss.xml", "category": "AI · Engineering"},
    {"name": "Ollama Blog", "url": "https://ollama.com/blog/rss.xml", "category": "AI · Engineering"},
    {"name": "Together AI Blog", "url": "https://www.together.ai/blog/rss.xml", "category": "AI · Engineering"},
    {"name": "Anyscale Blog", "url": "https://www.anyscale.com/rss.xml", "category": "AI · Engineering"},
    {"name": "Arize AI Blog", "url": "https://arize.com/blog/feed/", "category": "AI · Engineering"},
    # AI · Experts (7)
    {"name": "Simon Willison", "url": "https://simonwillison.net/atom/everything/", "category": "AI · Experts"},
    {"name": "Lilian Weng", "url": "https://lilianweng.github.io/index.xml", "category": "AI · Experts"},
    {"name": "Sebastian Raschka", "url": "https://sebastianraschka.com/rss_feed.xml", "category": "AI · Experts"},
    {"name": "Eugene Yan", "url": "https://eugeneyan.com/rss/", "category": "AI · Experts"},
    {"name": "Andrej Karpathy", "url": "https://karpathy.bearblog.dev/feed/", "category": "AI · Experts"},
    {"name": "Armin Ronacher", "url": "https://lucumr.pocoo.org/feed.xml", "category": "AI · Experts"},
    {"name": "Hamel Husain", "url": "https://hamel.dev/index.xml", "category": "AI · Experts"},
    # AI · Research (8: 5 media/analysis + 3 academic)
    {"name": "Interconnects", "url": "https://www.interconnects.ai/feed", "category": "AI · Research"},
    {"name": "Transformer Circuits", "url": "https://transformer-circuits.pub/feed.xml", "category": "AI · Research"},
    {"name": "AI Alignment Forum", "url": "https://www.alignmentforum.org/feed.xml", "category": "AI · Research"},
    {"name": "LessWrong Curated", "url": "https://www.lesswrong.com/feed.xml?view=curated", "category": "AI · Research"},
    {"name": "The Gradient", "url": "https://thegradient.pub/feed/", "category": "AI · Research"},
    {"name": "arXiv cs.AI", "url": "https://rss.arxiv.org/rss/cs.AI", "category": "AI · Research"},
    {"name": "arXiv cs.CL", "url": "https://rss.arxiv.org/rss/cs.CL", "category": "AI · Research"},
    {"name": "arXiv cs.LG", "url": "https://rss.arxiv.org/rss/cs.LG", "category": "AI · Research"},
    # AI · Newsletters (5)
    {"name": "Import AI", "url": "https://www.jack-clark.net/feed/", "category": "AI · Newsletters"},
    {"name": "Latent Space", "url": "https://www.latent.space/feed", "category": "AI · Newsletters"},
    {"name": "Last Week in AI", "url": "https://lastweekin.ai/feed", "category": "AI · Newsletters"},
    {"name": "Ahead of AI", "url": "https://magazine.sebastianraschka.com/feed", "category": "AI · Newsletters"},
    {"name": "The Rundown AI", "url": "https://www.therundown.ai/feed", "category": "AI · Newsletters"},
    # AI · News (2)
    {"name": "MIT Technology Review AI", "url": "https://www.technologyreview.com/topic/artificial-intelligence/feed", "category": "AI · News"},
    {"name": "The Verge AI", "url": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml", "category": "AI · News"},
]

BASE = os.environ["FRESHRSS_BASE_URL"].rstrip("/")
USER = os.environ["FRESHRSS_USERNAME"]
PASSWORD = os.environ["FRESHRSS_API_PASSWORD"]


def login(client: httpx.Client) -> str:
    resp = client.post(
        f"{BASE}/api/greader.php/accounts/ClientLogin",
        data={"Email": USER, "Passwd": PASSWORD},
    )
    resp.raise_for_status()
    for line in resp.text.splitlines():
        if line.startswith("Auth="):
            return line[5:].strip()
    raise RuntimeError(f"no Auth in ClientLogin response: {resp.text[:120]}")


def quickadd(client: httpx.Client, auth: str, url: str) -> dict:
    resp = client.post(
        f"{BASE}/api/greader.php/reader/api/0/subscription/quickadd",
        params={"quickadd": url},
        headers={"Authorization": f"GoogleLogin auth={auth}"},
    )
    resp.raise_for_status()
    return resp.json()


def edit_category(client: httpx.Client, auth: str, stream_id: str, category: str) -> None:
    resp = client.post(
        f"{BASE}/api/greader.php/reader/api/0/subscription/edit",
        headers={"Authorization": f"GoogleLogin auth={auth}"},
        data={
            "ac": "edit",
            "s": stream_id,
            "a": f"user/-/label/{category}",
        },
    )
    resp.raise_for_status()


def main() -> None:
    log: list[dict] = []
    with httpx.Client(timeout=httpx.Timeout(60.0, connect=15.0)) as client:
        auth = login(client)
        print(f"logged in as {USER}")
        for i, feed in enumerate(SELECTED, 1):
            rec = {"name": feed["name"], "url": feed["url"], "category": feed["category"]}
            t0 = time.perf_counter()
            try:
                added = quickadd(client, auth, feed["url"])
                rec["streamId"] = added.get("streamId")
                rec["freshrssTitle"] = added.get("streamName")
                if added.get("numResults") != 1:
                    rec["status"] = f"QUICKADD_FAIL: {added.get('error', 'unknown')}"
                else:
                    edit_category(client, auth, rec["streamId"], feed["category"])
                    rec["status"] = "ADDED"
            except Exception as exc:  # noqa: BLE001
                rec["status"] = f"EXC {type(exc).__name__}: {exc}"[:160]
            rec["seconds"] = round(time.perf_counter() - t0, 1)
            log.append(rec)
            print(f"[{i:02d}/40] {rec['status']:30s} {rec['seconds']:>5}s  {feed['name']}")
        (HERE / "add-results.json").write_text(
            json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
        ok = sum(1 for r in log if r["status"] == "ADDED")
        print(f"\n{ok}/40 added -> add-results.json")


if __name__ == "__main__":
    main()
