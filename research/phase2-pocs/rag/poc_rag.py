#!/usr/bin/env python3
"""PoC 09-rag-index: real local embeddings + sqlite-vec vector search +
FTS5 hybrid over 1,000 deterministic chunks (zh/en mixed).

Embedding: BAAI/bge-small-zh-v1.5 via fastembed (ONNX CPU, no torch).
Run: uv run --with fastembed --with sqlite-vec python poc_rag.py
"""
from __future__ import annotations

import resource
import sqlite3
import struct
import time

import sqlite_vec  # sqlite-vec loadable extension
from fastembed import TextEmbedding

N = 1000
TOPICS_EN = [
    ("retrieval augmented generation", "ground answers in retrieved documents", "rag"),
    ("quantized inference", "int8 weights cut memory at small accuracy cost", "quant"),
    ("agentic tool use", "models calling tools in a loop with approval", "agent"),
    ("attention kernels", "flash attention tiles the softmax computation", "kernels"),
    ("rlhf alignment", "preference data trains a reward model", "rlhf"),
]
TOPICS_ZH = [
    ("本地机器翻译", "在用户设备上运行的小型翻译模型", "翻译"),
    ("订阅聚合", "RSS 与 Atom 源的抓取与增量刷新", "订阅"),
    ("网页剪藏", "正文提取、净化与 Markdown 转换", "剪藏"),
    ("知识图谱", "笔记之间的链接与标签构成图结构", "图谱"),
    ("检索增强生成", "用检索到的文档为答案提供依据", "检索"),
]


def chunk_text(i: int) -> tuple[str, str, str]:
    t = (TOPICS_EN + TOPICS_ZH)[i % 10]
    lang = "en" if i % 10 < 5 else "zh"
    title = f"{t[0]} — chunk {i // 10}"
    body = f"{t[1]}. ({lang}) segment {i} of the corpus about {t[0]}."
    return t[2], title, body


def vec_sql(data: list[float]) -> bytes:
    return struct.pack(f"{len(data)}f", *data)


def main() -> None:
    t0 = time.perf_counter()
    print("loading embedding model (bge-small-zh-v1.5, ONNX)...")
    model = TextEmbedding("BAAI/bge-small-zh-v1.5")
    print(f"model ready in {time.perf_counter()-t0:.1f}s; peakRSS={resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024:.0f}MB")

    chunks = [chunk_text(i) for i in range(N)]
    t1 = time.perf_counter()
    texts = [f"{title}. {body}" for _, title, body in chunks]
    vecs = list(model.embed(texts, batch_size=64))
    embed_s = time.perf_counter() - t1
    print(f"embedded {N} chunks in {embed_s:.1f}s ({N/embed_s:.0f}/s)")

    db = sqlite3.connect(":memory:")
    db.enable_load_extension(True)
    sqlite_vec.load(db)
    db.execute("CREATE VIRTUAL TABLE vec_items USING vec0(chunk_id INTEGER PRIMARY KEY, embedding float[512])")
    db.execute("CREATE VIRTUAL TABLE fts USING fts5(chunk_id UNINDEXED, title, body, tokenize='trigram')")
    t2 = time.perf_counter()
    db.executemany("INSERT INTO vec_items VALUES (?, ?)", [(i, vec_sql(v[:512].tolist())) for i, v in enumerate(vecs)])
    db.executemany("INSERT INTO fts VALUES (?,?,?)", [(i, chunks[i][1], chunks[i][2]) for i in range(N)])
    print(f"index built in {time.perf_counter()-t2:.2f}s")

    queries = {
        "en→semantic": "how do I ground model answers in documents?",
        "zh→semantic": "怎样在设备上本地翻译文章？",
        "cross zh→en-doc": "量化模型能减少内存吗",
        "cross en→zh-doc": "extract clean article text from web pages",
    }
    for label, q in queries.items():
        qv = list(model.embed([q]))[0][:512]
        t3 = time.perf_counter()
        k = 5
        hits = db.execute(
            "SELECT v.chunk_id, distance FROM vec_items v WHERE v.embedding MATCH ? AND k = ? ORDER BY distance",
            (vec_sql(qv.tolist()), k),
        ).fetchall()
        fts_rows = db.execute(
            "SELECT chunk_id, bm25(fts) FROM fts WHERE fts MATCH ? LIMIT 5", (f'"{q}"',)
        ).fetchall()
        dt = (time.perf_counter() - t3) * 1000
        top = hits[0] if hits else None
        fts_hit = "FTS-hit" if fts_rows else "FTS-empty"
        print(f"[{label}] {dt:.0f}ms {fts_hit} top=chunk{top[0]}(d={top[1]:.3f}) '{chunks[top[0]][1][:36]}'")

    # hybrid: reciprocal rank fusion of vector + FTS result sets
    qv = list(model.embed(["量化模型能减少内存吗"]))[0][:512]
    vres = [r[0] for r in db.execute(
        "SELECT chunk_id FROM vec_items WHERE embedding MATCH ? AND k = 10 ORDER BY distance",
        (vec_sql(qv.tolist()),)).fetchall()]
    fres = [r[0] for r in db.execute(
        "SELECT chunk_id FROM fts WHERE fts MATCH ? LIMIT 10", ("量化 OR 内存",)).fetchall()]
    rrf: dict[int, float] = {}
    for rank, cid in enumerate(vres):
        rrf[cid] = rrf.get(cid, 0) + 1 / (60 + rank + 1)
    for rank, cid in enumerate(fres):
        rrf[cid] = rrf.get(cid, 0) + 1 / (60 + rank + 1)
    fused = sorted(rrf, key=rrf.get, reverse=True)[:5]
    print("hybrid RRF top-5:", [(f"chunk{c}", chunks[c][1][:30]) for c in fused])

    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    print(f"peakRSS={rss:.0f}MB total={time.perf_counter()-t0:.1f}s")


if __name__ == "__main__":
    main()
