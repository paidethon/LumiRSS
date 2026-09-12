"""Read-only relationship graph (phase2 G8).

Nodes/edges are DERIVED on request from real relations — item_tags,
workspace_items, and vault wikilinks — there is no second graph store.
A workspace scope applies to EVERY edge type: only workspace members,
their tags, and wikilinks touching member notes are included (P0-10c).
Wikilinks resolve to the real target note's identity when exactly one
indexed note matches (by path, then by unique title); otherwise the
target stays an explicitly ``unresolved`` node — never a silent fake
content node. The response is capped (default 2000 nodes) and reports
both the pre-truncation candidate total and the returned count
(P0-10d). The graph is never the only access path: the tag list and
workspace views carry the same information as text.
"""

import json
from typing import Any

from lumirss.storage import Database

_MAX_NODES = 2000


def _truncate(
    nodes: dict[str, dict[str, Any]],
    edges: list[dict[str, Any]],
    max_nodes: int,
) -> dict[str, Any]:
    total = len(nodes)
    truncated = total > max_nodes
    if truncated:
        ranked = sorted(nodes.values(), key=lambda n: (-n["degree"], n["ref"]))
        keep = {n["ref"] for n in ranked[:max_nodes]}
        edges = [e for e in edges if e["src"] in keep and e["dst"] in keep]
        nodes = {ref: nodes[ref] for ref in keep}
    return {
        "nodes": list(nodes.values()),
        "edges": edges,
        "truncated": truncated,
        "totalNodes": total,
        "returnedNodes": len(nodes),
    }


async def build_graph(db: Database, *, scope: str, max_nodes: int = _MAX_NODES) -> dict[str, Any]:
    """Derive nodes/edges for a scope: all | workspace:<id>."""
    await db.migrate()
    workspace_scope = scope[10:] if scope.startswith("workspace:") else None

    members: set[str] | None = None
    if workspace_scope is not None:
        member_rows = await db.fetch_all(
            "SELECT item_ref FROM workspace_items WHERE workspace_id = ?",
            (workspace_scope,),
        )
        members = {str(row["item_ref"]) for row in member_rows}

    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []

    def add_node(ref: str, label: str, kind: str) -> None:
        if ref not in nodes:
            nodes[ref] = {"ref": ref, "label": label or ref, "kind": kind, "degree": 0}

    def add_edge(src: str, dst: str, kind: str) -> None:
        edges.append({"src": src, "dst": dst, "kind": kind})
        if src in nodes:
            nodes[src]["degree"] += 1
        if dst in nodes:
            nodes[dst]["degree"] += 1

    # note identity maps for wikilink resolution (path first, then unique
    # title); ambiguity deliberately resolves to explicit-unresolved.
    note_rows = await db.fetch_all(
        "SELECT item_uuid, rel_path, title, wikilinks FROM obsidian_notes"
    )
    uuid_by_path: dict[str, str] = {}
    title_hits: dict[str, list[str]] = {}
    for row in note_rows:
        uuid_by_path.setdefault(str(row["rel_path"]), str(row["item_uuid"]))
        title_hits.setdefault(str(row["title"]), []).append(str(row["item_uuid"]))

    def resolve_wikilink(target: str) -> str | None:
        clean = target.strip().lstrip("#")
        direct = uuid_by_path.get(clean)
        if direct is not None:
            return direct
        hits = title_hits.get(clean, [])
        return hits[0] if len(hits) == 1 else None

    # item→tag edges (active bindings only; scope = members' bindings).
    tag_rows = await db.fetch_all(
        "SELECT it.item_ref AS ref, t.name AS name FROM item_tags it JOIN tags t ON t.id = it.tag_id WHERE it.status = 'active'"
    )
    for row in tag_rows:
        ref = str(row["ref"])
        if members is not None and ref not in members:
            continue
        tag_ref = f"tag:{row['name']}"
        add_node(ref, ref, _kind_of(ref))
        add_node(str(tag_ref), f"#{row['name']}", "tag")
        add_edge(ref, str(tag_ref), "tagged")

    # item→workspace edges.
    ws_params: tuple = ()
    ws_where = ""
    if workspace_scope is not None:
        ws_where = " WHERE w.id = ?"
        ws_params = (workspace_scope,)
    ws_rows = await db.fetch_all(
        "SELECT wi.item_ref AS ref, w.id AS workspace_id, w.name AS workspace_name FROM workspace_items wi JOIN workspaces w ON w.id = wi.workspace_id"
        + ws_where,
        ws_params,
    )
    for row in ws_rows:
        ref = str(row["ref"])
        ws_ref = f"ws:{row['workspace_id']}"
        add_node(ref, ref, _kind_of(ref))
        add_node(str(ws_ref), str(row["workspace_name"]), "workspace")
        add_edge(ref, str(ws_ref), "in-workspace")

    # note→note wikilink edges (only notes in scope emit edges).
    for row in note_rows:
        ref = f"library:{row['item_uuid']}"
        if members is not None and ref not in members:
            continue
        rel_path = str(row["rel_path"])
        add_node(ref, rel_path, "obsidian_note")
        try:
            targets = json.loads(str(row["wikilinks"]))
        except ValueError:
            targets = []
        for target in targets if isinstance(targets, list) else []:
            target_text = str(target)
            resolved_uuid = resolve_wikilink(target_text)
            if resolved_uuid is None:
                target_ref = f"wiki:{rel_path}:{target_text}"
                add_node(target_ref, target_text, "unresolved")
            elif resolved_uuid == str(row["item_uuid"]):
                continue  # self-link: no node, no edge
            else:
                target_ref = f"library:{resolved_uuid}"
                add_node(target_ref, target_text, "obsidian_note")
            add_edge(ref, target_ref, "wikilink")

    # Human labels for item nodes (best effort; refs stay honest labels).
    lib_labels = await db.fetch_all(
        "SELECT i.uuid, COALESCE(b.title, c.title, o.title, i.kind) AS label FROM library_items i LEFT JOIN library_bookmarks b ON b.item_uuid = i.uuid LEFT JOIN library_clips c ON c.item_uuid = i.uuid LEFT JOIN obsidian_notes o ON o.item_uuid = i.uuid"
    )
    for row in lib_labels:
        ref = f"library:{row['uuid']}"
        if ref in nodes and row["label"]:
            nodes[ref]["label"] = str(row["label"])
    rss_labels = await db.fetch_all(
        "SELECT entry_ref, title FROM search_entries LIMIT 1000"
    )
    for row in rss_labels:
        ref = str(row["entry_ref"])
        if ref in nodes and row["title"]:
            nodes[ref]["label"] = str(row["title"])

    return _truncate(nodes, edges, max_nodes)


def _kind_of(ref: str) -> str:
    if ref.startswith("rss:"):
        return "rss"
    if ref.startswith("library:"):
        return "library"
    return "unknown"
