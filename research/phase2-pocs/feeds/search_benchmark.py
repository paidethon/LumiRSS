#!/usr/bin/env python3
"""Search latency benchmark against the running dev BFF (fixed queries)."""
from __future__ import annotations

import statistics
import time

import httpx

QUERIES = ["AI", "LLM", "agent", "inference", "reasoning", "RAG", "vision", "robotics"]
ROUNDS = 15
BASE = "http://127.0.0.1:8000"


def main() -> None:
    latencies: dict[str, list[float]] = {}
    with httpx.Client(timeout=30.0) as c:
        for q in QUERIES:
            latencies[q] = []
            for _ in range(ROUNDS):
                t0 = time.perf_counter()
                r = c.get(f"{BASE}/api/v1/search", params={"q": q, "limit": 20})
                dt = (time.perf_counter() - t0) * 1000
                if r.status_code != 200:
                    print(f"  {q}: HTTP {r.status_code} {r.text[:80]}")
                    break
                latencies[q].append(dt)
    print(f"{'query':<10} {'p50':>7} {'p95':>7} {'max':>7}   hits(first)")
    for q, vals in latencies.items():
        if not vals:
            continue
        vals.sort()
        p50 = statistics.median(vals)
        p95 = vals[int(len(vals) * 0.95) - 1] if len(vals) > 1 else vals[0]
        with httpx.Client(timeout=30.0) as c:
            hits = c.get(f"{BASE}/api/v1/search", params={"q": q, "limit": 20}).json()
        total = hits.get("total", hits.get("entryCount", "?"))
        print(f"{q:<10} {p50:>6.1f}ms {p95:>6.1f}ms {max(vals):>6.1f}ms   total={total}")


if __name__ == "__main__":
    main()
