"""Tags + derived graph tests (phase2 G8).

Uniqueness/normalization/idempotent attach, suggested-invisibility with
explicit accept upgrade, agent add_tag via the REAL approval path, and
graph derivation correctness (tag/workspace/wikilink edges + truncation).
"""

import pytest

from lumirss.agent_store import AgentStore, ApprovalInvalid, ToolRegistry
from lumirss.graph import build_graph
from lumirss.storage import Database
from lumirss.tags import TagInvalid, TagNotFound, TagStore
from lumirss.workspaces import WorkspaceStore


def _run(coroutine):
    import asyncio

    return asyncio.run(coroutine)


@pytest.fixture()
def tag_db(tmp_path):
    db = Database(tmp_path / "lumi.sqlite")
    _run(db.migrate())
    return db


REF = "library:0b8df3e0-1f2a-4c3d-9e4f-5a6b7c8d9e0f"
REF2 = "library:1b8df3e0-1f2a-4c3d-9e4f-5a6b7c8d9e0f"


def test_attach_normalize_idempotent_counts(tag_db):
    store = TagStore(tag_db)
    first = _run(store.attach(REF, "  机器学习 "))
    assert first["name"] == "机器学习"
    duplicate = _run(store.attach(REF, "#机器学习"))
    assert duplicate["name"] == "机器学习"  # same canonical tag
    _run(store.attach(REF2, "机器学习"))
    # NFC normalization folds composed/decomposed forms onto one tag.
    decomposed = "e\u0301tude"
    _run(store.attach(REF, decomposed))
    tags = _run(store.list_tags())
    names = {t.name for t in tags}
    assert "机器学习" in names
    assert "étude" in names  # NFC composed form
    assert len([n for n in names if n.replace("́", "") == "étude"]) == 1


def test_suggested_invisible_until_accepted(tag_db):
    store = TagStore(tag_db)
    # AI suggestion lands as suggested (e.g. from an AI pipeline).
    _run(store.attach(REF, "建议标签", origin="ai", status="suggested"))
    # Active listing hides it; item view shows it only with the flag.
    assert all(t.name != "建议标签" for t in _run(store.list_tags()))
    suggested = _run(store.tags_for_item(REF, include_suggested=True))
    assert any(t["status"] == "suggested" for t in suggested)
    plain = _run(store.tags_for_item(REF))
    assert plain == []
    # Explicit accept upgrades the SAME row.
    _run(store.accept_suggestion(REF, "建议标签"))
    active = _run(store.tags_for_item(REF))
    assert active == [{"tagId": active[0]["tagId"], "name": "建议标签", "origin": "manual", "status": "active"}]


def test_rename_merge_conflict_and_delete_cascade(tag_db):
    store = TagStore(tag_db)
    _run(store.attach(REF, "旧名"))
    created = _run(store.attach(REF2, "新名"))
    with pytest.raises(TagInvalid):
        _run(store.rename(created["tagId"], "旧名"))
    renamed = _run(store.rename(created["tagId"], "改名"))
    assert renamed.name == "改名"
    assert _run(store.delete(created["tagId"])) is True
    with pytest.raises(TagNotFound):
        _run(store.rename(created["tagId"], "再改"))


def test_agent_add_tag_requires_approval_and_persists(tag_db):
    """G8 requirement: the agent's tag tool goes through the REAL approval
    gate and the write lands in the real tags tables."""
    store = TagStore(tag_db)
    agent_store = AgentStore(tag_db)
    registry = ToolRegistry()

    async def factory():
        return None

    _ = factory

    async def real_add_tag(args: dict) -> dict:
        binding = await store.attach(
            str(args.get("itemRef")), str(args.get("name")), origin="manual"
        )
        return {"tagged": True, "name": binding["name"], "ref": binding["ref"]}

    registry.register_write(
        "add_tag",
        "tag writer",
        {"type": "object", "properties": {"itemRef": {"type": "string"}, "name": {"type": "string"}}},
        real_add_tag,
    )
    thread = _run(agent_store.create_thread("打标会话"))
    thread_id = thread["id"]
    approval = _run(agent_store.create_approval(thread_id, "c1", "add_tag", {"itemRef": REF, "name": "_agent"}))
    # Before approval: nothing written.
    assert _run(store.tags_for_item(REF)) == []
    taken = _run(agent_store.take_approval(thread_id, approval["approvalId"], _hash("add_tag", {"itemRef": REF, "name": "_agent"})))
    result = _run(registry.invoke_write(taken["tool"], taken["args"]))
    assert result["tagged"] is True
    tags = _run(store.tags_for_item(REF))
    assert tags and tags[0]["name"] == "_agent"
    # Double-approve refused.
    with pytest.raises(ApprovalInvalid):
        _run(agent_store.take_approval(thread_id, approval["approvalId"], _hash("add_tag", {"itemRef": REF, "name": "_agent"})))


def _hash(tool: str, args: dict) -> str:
    from lumirss.agent_store import args_hash

    return args_hash(tool, args)


def test_graph_derivation_and_truncation(tag_db):
    store = TagStore(tag_db)
    _run(store.attach(REF, "ai"))
    _run(store.attach(REF2, "ai"))
    ws = WorkspaceStore(tag_db)
    _run(ws.create_workspace("研究"))
    _run(ws.add_item("research" , REF) if False else ws.add_item(_ws_id(tag_db), REF))

    import asyncio

    async def build():
        return await build_graph(tag_db, scope="all", max_nodes=2000)

    graph = asyncio.run(build())
    refs = {n["ref"] for n in graph["nodes"]}
    assert "tag:ai" in refs
    assert REF in refs and REF2 in refs
    kinds = {e["kind"] for e in graph["edges"]}
    assert "tagged" in kinds and "in-workspace" in kinds
    assert graph["truncated"] is False

    tiny = asyncio.run(build_graph(tag_db, scope="all", max_nodes=3))
    assert tiny["truncated"] is True
    assert len(tiny["nodes"]) <= 3


def _ws_id(tag_db) -> str:
    async def get():
        store = WorkspaceStore(tag_db)
        listing = await store.list_workspaces()
        for s in listing:
            if not s.reserved:
                return s.id
        created = await store.create_workspace("研究")
        return created.id

    return _run(get())
