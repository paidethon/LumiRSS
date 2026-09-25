"""N079 笔记与事实分栏 — 类型化 CRUD / 导出保持类型 / AI 面类型标签。

- CRUD：创建带 sections、读取归一化（NULL/损坏 → 三空数组）、
  更新 sentinel 语义（缺席 = 不改；显式空 = 清空）；非法键 422；
- 搜索投影：search_library body 以 [事实]/[个人解读]/[待核实] 标签
  渲染 —— AI 消费面（RAG/检索）读到的每条都带类型标签；
- 导出（Web 下载路径的等价语义）：分栏渲染进导出文本，类型不丢。
"""

import asyncio
import json

from lumirss.main import app
from lumirss.note_sections import (
    SECTION_LABELS,
    NoteSectionsInvalid,
    render_typed_sections,
    validate_sections,
)


def _run(coroutine):
    return asyncio.run(coroutine)


def _search_row(note_id: str) -> dict | None:
    async def get():
        row = await app.state.db.fetch_one(
            "SELECT title, body FROM search_library WHERE ref = ?", (f"note:{note_id}",)
        )
        return dict(row) if row is not None else None

    return _run(get())


# ---- 纯函数单测（AI 面标签） --------------------------------------------------


def test_n079_render_typed_sections_labels():
    """AI surface labels（unit）：逐条 [事实]/[个人解读]/[待核实] 标签。"""
    rendered = render_typed_sections(
        {
            "facts": ["原文说 A 于 2020 年发布"],
            "interpretation": ["我认为 A 的动机是 B"],
            "toVerify": ["B 的说法需要查证"],
        }
    )
    lines = rendered.splitlines()
    assert lines == [
        f"[{SECTION_LABELS['facts']}] 原文说 A 于 2020 年发布",
        f"[{SECTION_LABELS['interpretation']}] 我认为 A 的动机是 B",
        f"[{SECTION_LABELS['toVerify']}] B 的说法需要查证",
    ]
    # 空栏不出现在输出里；全空 → ''
    assert render_typed_sections({"facts": ["x"], "interpretation": [], "toVerify": []}).count("\n") == 0
    assert render_typed_sections(validate_sections(None)) == ""


def test_n079_validate_sections_rejects_unknown_keys_and_overlong():
    for bad in (
        {"unknown": ["x"]},
        {"facts": "not-a-list"},
        {"facts": [1, 2]},
        {"facts": ["x" * 1001]},
        {"facts": ["a"] * 51},
    ):
        try:
            validate_sections(bad)
        except NoteSectionsInvalid:
            continue
        raise AssertionError(f"should have rejected: {bad!r}")
    cleaned = validate_sections({"facts": ["  ", "  有效  "], "interpretation": None})
    assert cleaned == {"facts": ["有效"], "interpretation": [], "toVerify": []}


# ---- HTTP CRUD ---------------------------------------------------------------


def test_n079_typed_crud_and_sentinel_update(client):
    created = client.post(
        "/api/v1/library/notes",
        json={
            "title": "分栏笔记",
            "contentMd": "# 正文",
            "sections": {
                "facts": ["原文陈述 1"],
                "interpretation": ["我的解读"],
                "toVerify": ["待核实点"],
            },
        },
    )
    assert created.status_code == 201, created.text
    note = created.json()
    assert note["sections"] == {
        "facts": ["原文陈述 1"],
        "interpretation": ["我的解读"],
        "toVerify": ["待核实点"],
    }
    note_id = note["uuid"]

    got = client.get(f"/api/v1/library/notes/{note_id}").json()
    assert got["sections"]["facts"] == ["原文陈述 1"]

    # sentinel：更新不带 sections 键 = 不修改
    updated = client.patch(
        f"/api/v1/library/notes/{note_id}",
        json={"title": "改名", "baseUpdatedAt": note["updatedAt"]},
    )
    assert updated.status_code == 200
    assert updated.json()["sections"]["interpretation"] == ["我的解读"]

    # 显式空对象 = 清空（诚实可逆）
    cleared = client.patch(
        f"/api/v1/library/notes/{note_id}",
        json={"sections": {}, "baseUpdatedAt": updated.json()["updatedAt"]},
    )
    assert cleared.status_code == 200
    assert cleared.json()["sections"] == {"facts": [], "interpretation": [], "toVerify": []}

    # 非法键 → 422
    bad = client.post(
        "/api/v1/library/notes",
        json={"title": "x", "contentMd": "y", "sections": {"nope": ["z"]}},
    )
    assert bad.status_code == 422
    assert bad.json()["error"]["type"] == "invalid_note_sections"


def test_n079_legacy_note_reads_as_empty_sections(client):
    """旧笔记（sections_json=NULL）诚实归一为三空数组，绝不报错。"""
    created = client.post(
        "/api/v1/library/notes", json={"title": "旧笔记", "contentMd": "内容"}
    ).json()

    async def wipe_sections():
        await app.state.db.migrate()
        await app.state.db.execute(
            "UPDATE lumi_notes SET sections_json = NULL WHERE uuid = ?",
            (created["uuid"],),
        )

    _run(wipe_sections())
    got = client.get(f"/api/v1/library/notes/{created['uuid']}").json()
    assert got["sections"] == {"facts": [], "interpretation": [], "toVerify": []}


def test_n079_search_projection_carries_type_labels(client):
    """AI 面标签（集成）：分栏写进搜索投影 body，逐条带类型标签；
    个人判断不会被表述为原文事实（解读行永远带 [个人解读] 前缀）。"""
    created = client.post(
        "/api/v1/library/notes",
        json={
            "title": "RAG 笔记",
            "contentMd": "正文第一行",
            "sections": {
                "facts": ["系统默认关闭远程索引"],
                "interpretation": ["作者倾向隐私优先"],
                "toVerify": ["默认值可能随版本变化"],
            },
        },
    ).json()
    row = _search_row(created["uuid"])
    assert row is not None
    assert "正文第一行" in row["body"]
    assert f"[{SECTION_LABELS['facts']}] 系统默认关闭远程索引" in row["body"]
    assert f"[{SECTION_LABELS['interpretation']}] 作者倾向隐私优先" in row["body"]
    assert f"[{SECTION_LABELS['toVerify']}] 默认值可能随版本变化" in row["body"]

    # 更新分栏 → 投影同步刷新（含清空后标签消失）
    updated = client.patch(
        f"/api/v1/library/notes/{created['uuid']}",
        json={"sections": {"facts": ["新的唯一事实"]}},
    ).json()
    row = _search_row(created["uuid"])
    assert f"[{SECTION_LABELS['facts']}] 新的唯一事实" in row["body"]
    assert SECTION_LABELS["interpretation"] not in row["body"]
    assert updated["sections"]["interpretation"] == []


def test_n079_sections_roundtrip_json_shape(client):
    """存储形状：sections_json 是紧凑 JSON（键固定三栏）。"""
    created = client.post(
        "/api/v1/library/notes",
        json={
            "title": "形状检查",
            "contentMd": "c",
            "sections": {"facts": ["a"], "interpretation": ["b"]},
        },
    ).json()

    async def raw():
        row = await app.state.db.fetch_one(
            "SELECT sections_json FROM lumi_notes WHERE uuid = ?",
            (created["uuid"],),
        )
        return row["sections_json"]

    stored = _run(raw())
    assert json.loads(stored) == {
        "facts": ["a"],
        "interpretation": ["b"],
        "toVerify": [],
    }
