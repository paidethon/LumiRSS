"""N082 翻译数字校验 —— verify_numbers 纯后验 + GET translation-verification。

覆盖：数字 token 提取（千分位/小数/%；CJK 数字明确不在范围）、
missing/changed/added 三种差异、上下文 ≤40 字符、总条数上限 10；
端点侧：逐块定位、修订块是人类定稿（不挑刺）、旧行无源文本诚实
标记、language 过滤。全程零 provider 调用（纯只读端点）。
"""

import asyncio

from fastapi.testclient import TestClient

from lumirss.ai_translation_verification import (
    MAX_FINDINGS,
    extract_number_tokens,
    verify_numbers,
)
from lumirss.entryref import encode_entry_ref
from lumirss.main import app
from lumirss.storage import Database

run = asyncio.run

REF = encode_entry_ref("tag:google.com,2005:reader/item/0000000000000082")


# ---------------------------------------------------------------------------
# token 提取
# ---------------------------------------------------------------------------


def test_extract_numbers_integers_percent_thousands_decimals():
    text = "In 2024, 3,500 users (58%) paid $1,234.56 each."
    assert extract_number_tokens(text) == ["2024", "3,500", "58%", "1,234.56"]


def test_extract_numbers_cjk_numerals_out_of_scope():
    # 中文数字（一/三/两）不在提取范围 —— 诚实声明的能力边界。
    assert extract_number_tokens("三个人，两次失败。") == []
    assert extract_number_tokens("二〇二四年") == []


def test_verify_missing_number():
    findings = verify_numbers(
        "Sales rose 45% in 2023 with steady demand.",
        "2023 年销售额上升，需求平稳。",
    )
    assert [f["kind"] for f in findings] == ["missing"]
    assert findings[0]["token"] == "45%"


def test_verify_changed_percentage():
    # 50% → 60%：单字符漂移 → 合并为一条 changed（而非 missing+added）。
    findings = verify_numbers("Profit grew by 50% last year.", "去年利润增长了 60%。")
    assert [f["kind"] for f in findings] == ["changed"]
    assert findings[0]["token"] == "50%"
    assert findings[0]["sourceContext"]
    assert "60%" in findings[0]["translatedContext"]


def test_verify_added_number():
    findings = verify_numbers(
        "The team added new sites and pages.",
        "团队增加了 3 个站点和 120 个页面。",
    )
    kinds = sorted(f["kind"] for f in findings)
    assert kinds == ["added", "added"]
    tokens = sorted(f["token"] for f in findings)
    assert tokens == ["120", "3"]


def test_verify_contexts_bounded_at_40_chars():
    source = "x" * 200 + " 42 " + "y" * 200
    findings = verify_numbers(source, "译文没有数字")
    assert len(findings) == 1
    assert len(findings[0]["sourceContext"]) <= 40
    assert findings[0]["token"] in findings[0]["sourceContext"]


def test_verify_capped_at_ten_findings():
    source = " ".join(f"point{n}" for n in range(15))
    findings = verify_numbers(source, "译文一个数字都没有")
    assert len(findings) == MAX_FINDINGS


def test_verify_clean_translation_returns_empty():
    assert (
        verify_numbers(
            "Revenue was 3,500 units (12%) in 2024.",
            "2024 年收入为 3,500 台（12%）。",
        )
        == []
    )


# ---------------------------------------------------------------------------
# GET /translation-verification 端点
# ---------------------------------------------------------------------------


def _wire(tmp_path) -> Database:
    db = Database(tmp_path / "lumi.sqlite")
    run(db.migrate())
    return db


async def _seed_segment(
    db: Database,
    block_index: int,
    *,
    source: str | None,
    translated: str,
    revision: str | None = None,
    language: str = "zh-CN",
    created_at: str = "2026-09-20T00:00:00Z",
) -> None:
    await db.execute(
        """INSERT INTO ai_translation_segments (
        entry_ref, block_index, block_hash, provider, model, prompt_version,
        target_language, glossary_version, status, translated_text,
        source_text, user_revision, failure_type, created_at, updated_at)
        VALUES (?, ?, ?, 'ai', '', 'translation-segments-v1', ?, '', 'success',
        ?, ?, ?, NULL, ?, ?)""",
        (REF, block_index, f"h{block_index}", language, translated, source,
         revision, created_at, created_at),
    )


def test_verification_locates_findings_to_blocks(tmp_path):
    db = _wire(tmp_path)
    run(_seed_segment(
        db, 0,
        source="Sales rose 45% in 2023 with 3,500 users.",
        translated="2023 年销售额上升，拥有 3,500 名用户。",
    ))  # missing 45%
    run(_seed_segment(
        db, 1, source="Profit grew by 50%.", translated="利润增长了 60%。",
    ))  # changed
    run(_seed_segment(
        db, 2, source="Costs fell.", translated="成本下降了 12%。",
    ))  # added
    run(_seed_segment(
        db, 3, source="Human note 7.", translated="人工定稿 8。", revision="人工定稿 8。",
    ))  # 修订 = 人类定稿

    with TestClient(app) as client:
        app.state.db = db
        response = client.get(f"/api/v1/entries/{REF}/translation-verification")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["language"] == "zh-CN"
    by_index = {block["blockIndex"]: block for block in body["blocks"]}
    assert by_index[0]["verifiable"] is True
    assert [f["kind"] for f in by_index[0]["findings"]] == ["missing"]
    assert by_index[0]["findings"][0]["token"] == "45%"
    assert by_index[1]["verifiable"] is True
    assert [f["kind"] for f in by_index[1]["findings"]] == ["changed"]
    assert by_index[2]["verifiable"] is True
    assert [f["kind"] for f in by_index[2]["findings"]] == ["added"]
    # 修订块：人类定稿原样列出，verifiable=false 且无 findings。
    assert by_index[3]["verifiable"] is False
    assert by_index[3]["revised"] is True
    assert by_index[3]["reason"] == "user_revised"
    assert by_index[3]["findings"] == []
    assert body["totalFindings"] == 3


def test_verification_clean_translation_reports_no_findings(tmp_path):
    db = _wire(tmp_path)
    run(_seed_segment(
        db, 0,
        source="Revenue was 3,500 units (12%) in 2024.",
        translated="2024 年收入为 3,500 台（12%）。",
    ))
    with TestClient(app) as client:
        app.state.db = db
        body = client.get(
            f"/api/v1/entries/{REF}/translation-verification"
        ).json()
    assert body["totalFindings"] == 0
    assert body["blocks"][0]["findings"] == []


def test_verification_legacy_row_without_source_text_honest(tmp_path):
    db = _wire(tmp_path)
    run(_seed_segment(db, 4, source=None, translated="旧缓存行没有源文本。"))
    with TestClient(app) as client:
        app.state.db = db
        body = client.get(
            f"/api/v1/entries/{REF}/translation-verification"
        ).json()
    block = body["blocks"][0]
    assert block["verifiable"] is False
    assert block["reason"] == "source_text_unavailable"


def test_verification_language_filter(tmp_path):
    db = _wire(tmp_path)
    run(_seed_segment(db, 0, source="Grew 45%.", translated="增长 46%。",
                      language="en"))
    with TestClient(app) as client:
        app.state.db = db
        empty = client.get(
            f"/api/v1/entries/{REF}/translation-verification?language=zh-CN"
        ).json()
        matched = client.get(
            f"/api/v1/entries/{REF}/translation-verification?language=en"
        ).json()
    assert empty["blocks"] == []
    assert matched["blocks"][0]["findings"][0]["kind"] == "changed"


def test_verification_invalid_ref_rejected(tmp_path):
    db = _wire(tmp_path)
    with TestClient(app) as client:
        app.state.db = db
        response = client.get("/api/v1/entries/not-a-ref/translation-verification")
    assert response.status_code == 400
    assert response.json()["error"]["type"] == "invalid_entry_reference"
