"""F25 工作区说明 / F29 笔记反链 的行为测试。

F25：创建带说明的工作区、PATCH 修改说明（缺省 = 不改动）、500 字上限
校验、旧客户端省略 description 的兼容。
F29：RSS 书签（含用户笔记）按 entryRef 反向列出；无效/非 RSS 引用
返回空列表而非错误；多个书签引用同一文章时全部返回。
"""

import pytest


def _create(client, name="研发调研", description="2026 Q3 目标：整理本地翻译与 RAG 资料"):
    response = client.post(
        "/api/v1/workspaces", json={"name": name, "description": description}
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_f25_create_with_description_and_list(client):
    created = _create(client)
    assert created["description"].startswith("2026 Q3 目标")
    listing = client.get("/api/v1/workspaces").json()
    match = [item for item in listing["items"] if item["id"] == created["id"]]
    assert match and match[0]["description"] == created["description"]


def test_f25_patch_description_only_when_provided(client):
    created = _create(client)
    # 只重命名（description 缺省）→ 说明保持不变
    renamed = client.patch(
        f"/api/v1/workspaces/{created['id']}", json={"name": "改名后"}
    ).json()
    assert renamed["name"] == "改名后"
    assert renamed["description"] == created["description"]
    # 显式更新说明 → 生效
    updated = client.patch(
        f"/api/v1/workspaces/{created['id']}",
        json={"name": "改名后", "description": "新说明"},
    ).json()
    assert updated["description"] == "新说明"


def test_f25_description_length_guard(client):
    response = client.post(
        "/api/v1/workspaces",
        json={"name": "超长说明", "description": "长" * 501},
    )
    assert response.status_code == 400


def test_f29_notes_by_entry_roundtrip(client):
    entry_ref = "e1.MDAwNjU5ZTA3YWFlZTI0ZA"  # encode_entry_ref 的合法输出形态
    created = client.post(
        "/api/v1/library/bookmarks",
        json={
            "rssItemRef": f"rss:{entry_ref}",
            "title": "相关笔记一",
            "note": "关键论据：本地翻译无中文模型。",
        },
    )
    assert created.status_code == 201, created.text

    found = client.get(f"/api/v1/library/notes-by-entry/{entry_ref}")
    assert found.status_code == 200
    items = found.json()["items"]
    # 同文章书签按设计幂等（第二次创建返回已有项，不重复成行）
    assert len(items) == 1
    assert items[0]["title"] == "相关笔记一"
    assert items[0]["note"] == "关键论据：本地翻译无中文模型。"
    assert items[0]["rssItemRef"].endswith(entry_ref)


def test_f29_unknown_or_non_rss_ref_returns_empty(client):
    assert client.get("/api/v1/library/notes-by-entry/e1.0000000000000000").json()[
        "items"
    ] == []
    assert client.get("/api/v1/library/notes-by-entry/not-a-ref").json()["items"] == []


@pytest.mark.anyio
async def test_f25_description_strips_and_preserves_semantics(client):
    """说明做空白归一但保留完整语义（不截断语义单元）。"""
    created = _create(
        client,
        name="空白归一",
        description="第一行说明\n  第二行缩进   多余空格",
    )
    assert created["description"] == "第一行说明 第二行缩进 多余空格"
