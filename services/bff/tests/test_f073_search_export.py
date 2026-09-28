"""F073 引用清单导出 — CSV util 公式防护/CJK 转义、多页条数==总数、
空结果仅表头、cap 截断标注、导出不含正文全文（仅 excerpt）。"""

import asyncio

from lumirss.main import app
from lumirss.search_export import (
    build_csv,
    guard_cell,
    looks_like_formula,
)
from lumirss.storage import Database


def run(coroutine):
    return asyncio.run(coroutine)


def _seed(db, rows):
    async def _seed_inner():
        await db.migrate()
        for row in rows:
            await db.execute(
                "INSERT OR IGNORE INTO search_entries (item_id, entry_ref, feed_url, feed_title, title, author, url, content_text, published_at, read, starred, fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0)",
                row,
            )

    run(_seed_inner())


def _entry(n: int, term: str) -> tuple:
    return (
        f"i{n}",
        f"ref-{n}",
        "https://f.example/rss",
        "示例源",
        f"{term} 文章标题 {n}",
        "作者",
        f"https://f.example/{n}",
        f"{term} 正文内容。{term} 详细展开。" * 5,
        "2026-09-01T00:00:00Z",
    )


def test_f073_csv_util_formula_guard_and_escaping():
    # 公式特征：= + - @ 开头且不像纯数字 → 前置撇号
    assert looks_like_formula("=cmd") is True
    assert looks_like_formula("+123") is False  # 纯数字不防护
    assert looks_like_formula("-2,000") is False
    assert guard_cell("=cmd|' /C calc") == "'=cmd|' /C calc"
    assert guard_cell("普通文本") == "普通文本"
    # RFC 4180：逗号/引号/换行整体加引号，内部引号双写；CJK 原样保留
    csv = build_csv(["标题", "链接"], [["他说：\"你好\"，再见", "https://x/1"]])
    assert '"他说：""你好""，再见"' in csv
    assert "https://x/1" in csv
    multiline = build_csv(["a"], [["行1\n行2"]])
    assert '"行1\n行2"' in multiline


def test_f073_export_multi_page_count_truncation_and_excerpt_only(client):
    db = Database(app.state.db._path) if hasattr(app.state.db, "_path") else None
    db = app.state.db
    _seed(db, [_entry(n, "alpha") for n in range(12)])

    # 多页（默认 cap=500 > 12）：导出条数 == 命中总数；dryRun 报真实总数
    dry = client.post(
        "/api/v1/search/export", json={"q": "alpha", "dryRun": True}
    )
    assert dry.status_code == 200, dry.text
    assert dry.json() == {"total": 12, "scanned": 12, "capped": False}

    export = client.post("/api/v1/search/export", json={"q": "alpha"})
    assert export.status_code == 200
    assert "text/csv" in export.headers["content-type"]
    assert export.headers["x-lumi-total"] == "12"
    assert export.headers["x-lumi-truncated"] == "0"
    lines = [line for line in export.text.split("\n") if line != ""]
    assert len(lines) == 13  # 表头 + 12 行
    assert lines[0].startswith("标题,来源,日期,链接")
    # 负向：导出不含正文全文（无 excerpt 字段 → 无正文片段）
    assert "详细展开" not in export.text

    # 带 excerpt：截到 excerptChars（≤200），仍不含正文全文
    export2 = client.post(
        "/api/v1/search/export",
        json={"q": "alpha", "fields": ["title", "excerpt"], "excerptChars": 60},
    )
    rows2 = export2.text.strip().split("\n")
    assert rows2[0] == "标题,摘录"
    excerpt_cell = rows2[1].split(",", 1)[1].strip('"')
    assert len(excerpt_cell) <= 60 + 2  # 省略号余量

    # cap 截断标注（cap=5 < 12 命中）
    export3 = client.post("/api/v1/search/export", json={"q": "alpha", "cap": 5})
    assert export3.headers["x-lumi-truncated"] == "1"
    lines3 = [line for line in export3.text.split("\n") if line != ""]
    assert len(lines3) == 6

    # 空结果：200 + 仅表头
    empty = client.post("/api/v1/search/export", json={"q": "nosuchterm"})
    assert empty.status_code == 200
    assert [line for line in empty.text.split("\n") if line != ""] == ["标题,来源,日期,链接"]

    # markdown 格式：截断标注在文末引用行
    md = client.post(
        "/api/v1/search/export",
        json={"q": "alpha", "format": "markdown", "cap": 5},
    )
    assert "已截断" in md.text


# ---------------------------------------------------------------------------
# FIX-327 — 导出 CSV 公式前缀（含 TAB/CR/LF 前导形态）统一撇号转义，
# 原文可追溯（去一个前导撇号即还原）。


def test_fix327_formula_guard_tab_newline_prefixed_and_traceability():
    # TAB/CR/LF 前导的公式形态同样触发防护（表格软件求值前会剥掉它们）。
    assert looks_like_formula("\t=cmd") is True
    assert looks_like_formula("\r=1+1|' /C calc") is True
    assert looks_like_formula("\n\n@SUM(1)") is True
    assert guard_cell("\t=cmd") == "'\t=cmd"
    # 数值例外仍然成立（有意的可选择编码：数值列不转义、保持可排序）。
    assert looks_like_formula("-2,000") is False
    assert looks_like_formula("+123") is False
    assert looks_like_formula("\t-2,000") is False
    # 原文可追溯：被转义的值只前置恰好一个撇号，去掉即还原原值；
    # 未触发的值原样通过（不添加任何前缀）。
    for original in ("=cmd|' /C calc", "\t=1+1", "@x", "-1+1"):
        guarded = guard_cell(original)
        assert guarded.startswith("'")
        assert guarded[1:] == original
    assert guard_cell("普通文本") == "普通文本"
    # 全量输出层：TAB 前导公式进入 build_csv 后已被转义为文本。
    csv = build_csv(["标题"], [["\t=cmd('calc')"]])
    assert "'\t=cmd('calc')" in csv
    assert build_csv(["a"], [["\t=bad"]]).splitlines()[1].startswith("'")
