#!/usr/bin/env python3
"""Live-validate candidate AI/ML RSS feeds (fixed data file, fixed output dir).

For every candidate: fetch with redirects, record HTTP status / final URL /
content-type / latency, parse with feedparser, record feed format, title,
item count, latest item date. Writes report.json next to this script.

Usage:
    uv run --with feedparser --with httpx python validate_feeds.py
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import feedparser
import httpx

UA = "LumiRSS-FeedValidator/1.0 (+https://github.com/paidethon/LumiRSS)"

HERE = Path(__file__).resolve().parent

# Allowed output root: only this script's own directory.
try:
    HERE.relative_to(Path(__file__).resolve().parent)
except ValueError:  # pragma: no cover
    raise SystemExit("script path escapes allowed root")

CANDIDATES: list[dict] = [
    # --- AI Labs / Research orgs ---
    {"name": "OpenAI News", "url": "https://openai.com/news/rss.xml", "category": "labs"},
    {"name": "Google DeepMind Blog", "url": "https://deepmind.google/blog/rss.xml", "category": "labs"},
    {"name": "Google Research Blog", "url": "https://research.google/blog/rss/", "category": "labs"},
    {"name": "Google Blog AI", "url": "https://blog.google/technology/ai/rss/", "category": "labs"},
    {"name": "Microsoft Research", "url": "https://www.microsoft.com/en-us/research/feed/", "category": "labs"},
    {"name": "Apple ML Research", "url": "https://machinelearning.apple.com/rss/rss.xml", "category": "labs"},
    {"name": "NVIDIA Developer Blog", "url": "https://developer.nvidia.com/blog/feed/", "category": "labs"},
    {"name": "AWS Machine Learning Blog", "url": "https://aws.amazon.com/blogs/machine-learning/feed/", "category": "labs"},
    {"name": "BAIR Blog", "url": "https://bair.berkeley.edu/blog/feed.xml", "category": "labs"},
    {"name": "Meta AI Blog", "url": "https://ai.meta.com/blog/rss/", "category": "labs"},
    {"name": "Mistral AI News", "url": "https://mistral.ai/news/feed.xml", "category": "labs"},
    {"name": "Cohere Blog", "url": "https://cohere.com/blog/feed.xml", "category": "labs"},
    {"name": "Allen Institute for AI", "url": "https://allenai.org/blog/feed/rss.xml", "category": "labs"},
    {"name": "Anthropic News", "url": "https://www.anthropic.com/rss.xml", "category": "labs"},
    {"name": "Hugging Face Blog", "url": "https://huggingface.co/blog/feed.xml", "category": "labs"},
    # --- AI Engineering / infra ---
    {"name": "EleutherAI Blog", "url": "https://blog.eleuther.ai/rss.xml", "category": "engineering"},
    {"name": "Weights & Biases Blog", "url": "https://wandb.ai/feed.xml", "category": "engineering"},
    {"name": "Together AI Blog", "url": "https://www.together.ai/feed.xml", "category": "engineering"},
    {"name": "Modal Blog", "url": "https://modal.com/blog/feed.xml", "category": "engineering"},
    {"name": "Replicate Blog", "url": "https://blog.replicate.com/rss.xml", "category": "engineering"},
    {"name": "Groq Blog", "url": "https://groq.com/feed.xml", "category": "engineering"},
    {"name": "Ollama Blog", "url": "https://ollama.com/blog/rss.xml", "category": "engineering"},
    {"name": "vLLM Blog", "url": "https://blog.vllm.ai/feed.xml", "category": "engineering"},
    {"name": "LlamaIndex Blog", "url": "https://www.llamaindex.ai/blog/feed.xml", "category": "engineering"},
    {"name": "LangChain Blog", "url": "https://blog.langchain.dev/rss/", "category": "engineering"},
    {"name": "Roboflow Blog", "url": "https://blog.roboflow.com/rss/", "category": "engineering"},
    {"name": "Arize AI Blog", "url": "https://arize.com/feed.xml", "category": "engineering"},
    {"name": "Evidently AI Blog", "url": "https://www.evidentlyai.com/blog/feed.xml", "category": "engineering"},
    {"name": "Lightning AI", "url": "https://lightning.ai/feed.xml", "category": "engineering"},
    {"name": "Anyscale Blog", "url": "https://www.anyscale.com/rss.xml", "category": "engineering"},
    # --- Independent experts ---
    {"name": "Simon Willison", "url": "https://simonwillison.net/atom/everything/", "category": "experts"},
    {"name": "Lilian Weng", "url": "https://lilianweng.github.io/index.xml", "category": "experts"},
    {"name": "Chip Huyen", "url": "https://huyenchip.com/feed.xml", "category": "experts"},
    {"name": "Sebastian Raschka", "url": "https://sebastianraschka.com/rss_feed.xml", "category": "experts"},
    {"name": "Eugene Yan", "url": "https://eugeneyan.com/rss/", "category": "experts"},
    {"name": "Jay Alammar", "url": "https://jalammar.github.io/feed.xml", "category": "experts"},
    {"name": "Hamel Husain", "url": "https://hamel.dev/feed.xml", "category": "experts"},
    {"name": "Jeremy Howard / fast.ai", "url": "https://www.fast.ai/feeds.xml", "category": "experts"},
    {"name": "Vicki Boykis", "url": "https://vickiboykis.com/feed.xml", "category": "experts"},
    {"name": "Armin Ronacher", "url": "https://lucumr.pocoo.org/feed.xml", "category": "experts"},
    {"name": "Addy Osmani", "url": "https://addyosmani.com/feed.xml", "category": "experts"},
    {"name": "Andrej Karpathy", "url": "https://karpathy.bearblog.dev/feed/", "category": "experts"},
    # --- Research media / analysis ---
    {"name": "The Gradient", "url": "https://thegradient.pub/feed/", "category": "research-media"},
    {"name": "Import AI", "url": "https://importai.substack.com/feed", "category": "research-media"},
    {"name": "Interconnects", "url": "https://www.interconnects.ai/feed", "category": "research-media"},
    {"name": "Transformer Circuits", "url": "https://transformer-circuits.pub/feed.xml", "category": "research-media"},
    {"name": "LessWrong Curated", "url": "https://www.lesswrong.com/feed.xml?view=curated", "category": "research-media"},
    {"name": "AI Alignment Forum", "url": "https://www.alignmentforum.org/feed.xml", "category": "research-media"},
    # --- Newsletters / blogs ---
    {"name": "Latent Space", "url": "https://www.latent.space/feed", "category": "newsletters"},
    {"name": "Last Week in AI", "url": "https://lastweekin.ai/feed", "category": "newsletters"},
    {"name": "The Batch", "url": "https://www.deeplearning.ai/feed/", "category": "newsletters"},
    {"name": "Ahead of AI", "url": "https://magazine.sebastianraschka.com/feed", "category": "newsletters"},
    # --- News ---
    {"name": "MIT Technology Review AI", "url": "https://www.technologyreview.com/topic/artificial-intelligence/feed", "category": "news"},
    {"name": "TechCrunch AI", "url": "https://techcrunch.com/category/artificial-intelligence/feed/", "category": "news"},
    {"name": "Ars Technica AI", "url": "https://arstechnica.com/ai/feed/", "category": "news"},
    {"name": "The Verge AI", "url": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml", "category": "news"},
    {"name": "MarkTechPost", "url": "https://www.marktechpost.com/feed/", "category": "news"},
    {"name": "Towards Data Science", "url": "https://towardsdatascience.com/feed", "category": "news"},
    # --- Academic (<=5) ---
    {"name": "arXiv cs.AI", "url": "https://rss.arxiv.org/rss/cs.AI", "category": "academic"},
    {"name": "arXiv cs.CL", "url": "https://rss.arxiv.org/rss/cs.CL", "category": "academic"},
    {"name": "arXiv cs.LG", "url": "https://rss.arxiv.org/rss/cs.LG", "category": "academic"},
]


def latest_date(feed) -> str | None:
    dates = []
    for e in feed.entries:
        for attr in ("published_parsed", "updated_parsed"):
            t = e.get(attr)
            if t:
                dates.append(time.mktime(t))
                break
    if not dates:
        return None
    return time.strftime("%Y-%m-%d", time.gmtime(max(dates)))


def validate_one(client: httpx.Client, name: str, url: str) -> dict:
    rec: dict = {"name": name, "url": url}
    t0 = time.perf_counter()
    try:
        resp = client.get(url)
        latency = time.perf_counter() - t0
        rec.update(
            status=resp.status_code,
            finalUrl=str(resp.url),
            redirects=len(resp.history),
            contentType=resp.headers.get("content-type", "").split(";")[0],
            latencyS=round(latency, 2),
            bytes=len(resp.content),
        )
        if resp.status_code != 200:
            rec["verdict"] = "FAIL_HTTP"
            return rec
        feed = feedparser.parse(resp.content)
        version = feed.get("version", "")
        if not feed.entries:
            rec.update(bozo=str(feed.get("bozo", "")), verdict="FAIL_PARSE")
            return rec
        rec.update(
            feedType=version,
            feedTitle=feed.feed.get("title", "")[:80],
            itemCount=len(feed.entries),
            latestItem=latest_date(feed),
        )
        rec["verdict"] = "PASS"
    except Exception as exc:  # noqa: BLE001 — validator reports everything
        rec["verdict"] = "FAIL_EXC"
        rec["error"] = f"{type(exc).__name__}: {exc}"[:200]
    return rec


def main() -> None:
    out_path = HERE / "feed-validation-report.json"
    out: list[dict] = []
    with httpx.Client(
        follow_redirects=True,
        timeout=httpx.Timeout(25.0, connect=10.0),
        headers={
            "User-Agent": UA,
            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
        },
    ) as client:
        for i, cand in enumerate(CANDIDATES, 1):
            rec = validate_one(client, cand["name"], cand["url"])
            rec["category"] = cand["category"]
            rec["official"] = cand.get("official", True)
            out.append(rec)
            print(
                f"[{i:02d}/{len(CANDIDATES)}] {rec['verdict']:10s} {rec['name']}: "
                f"{rec.get('status', '-')} {rec.get('feedType', '')} "
                f"items={rec.get('itemCount', '-')} latest={rec.get('latestItem', '-')}"
            )
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    passed = sum(1 for r in out if r["verdict"] == "PASS")
    print(f"\n{passed}/{len(out)} PASS -> {out_path}")


if __name__ == "__main__":
    main()
