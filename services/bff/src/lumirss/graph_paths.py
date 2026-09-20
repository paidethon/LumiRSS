"""F077 关系路径查找 — 在派生图（标签/工作区/wikilink/手工关系边，
全部来自存储数据）上做 BFS 路径查找。

- 无向遍历（图谱语义：关联可双向走）；
- 每条路径自带 visited 集（环不会无限）；paths ≤5；深度 ≤ max_depth
  （默认/上限 4）；
- 端点缺失（已删除/不在图内）→ reachable:false（诚实，不造路径）；
- src==dst → 单节点平凡路径。
"""

import asyncio
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from lumirss.graph import build_graph

MAX_DEPTH = 4
MAX_PATHS = 5


@dataclass
class _Path:
    refs: list[str]
    edge_kinds: list[str] = field(default_factory=list)


async def find_paths(
    db: Any,
    *,
    src_ref: str,
    dst_ref: str,
    max_depth: int = MAX_DEPTH,
    max_paths: int = MAX_PATHS,
) -> dict[str, Any]:
    """BFS：返回 ≤max_paths 条 (节点序列 + 边类型序列)；不可达 →
    {paths: [], reachable: False}。"""
    await db.migrate()
    graph = await build_graph(db, scope="all")
    # build_graph 返回节点列表 → 以 ref 为键建索引
    nodes: dict[str, dict[str, Any]] = {str(n["ref"]): n for n in graph["nodes"]}
    if src_ref == dst_ref:
        if src_ref not in nodes:
            return {"paths": [], "reachable": False}
        node = nodes[src_ref]
        return {
            "paths": [
                {
                    "nodes": [{"ref": src_ref, "label": node["label"], "kind": node["kind"]}],
                    "edgeKinds": [],
                }
            ],
            "reachable": True,
        }

    # 邻接表（无向）：src -> [(dst, kind)]
    adjacency: dict[str, list[tuple[str, str]]] = {}
    for edge in graph["edges"]:
        src, dst, kind = str(edge["src"]), str(edge["dst"]), str(edge["kind"])
        adjacency.setdefault(src, []).append((dst, kind))
        adjacency.setdefault(dst, []).append((src, kind))

    if src_ref not in nodes or dst_ref not in nodes:
        return {"paths": [], "reachable": False}

    found: list[_Path] = []
    # BFS 队列元素：当前路径（refs + 边类型）+ 路径内 visited 集
    queue: deque[tuple[list[str], list[str], set[str]]] = deque()
    queue.append(([src_ref], [], {src_ref}))
    while queue and len(found) < max_paths:
        refs, kinds, visited = queue.popleft()
        depth = len(kinds)
        if depth >= max_depth:
            continue
        last = refs[-1]
        for neighbor, kind in adjacency.get(last, []):
            if neighbor in visited:
                continue  # 环：本路径内已访问 → 跳过（终止保证）
            new_refs = refs + [neighbor]
            new_kinds = kinds + [kind]
            new_visited = visited | {neighbor}
            if neighbor == dst_ref:
                found.append(_Path(new_refs, new_kinds))
                if len(found) >= max_paths:
                    break
                continue
            queue.append((new_refs, new_kinds, new_visited))
    # 统一 BFS 层序可能乱掉发现顺序——按 (长度, refs) 稳定排序后截断
    found.sort(key=lambda p: (len(p.refs), p.refs))
    paths = []
    for path in found[:max_paths]:
        paths.append(
            {
                "nodes": [
                    {
                        "ref": ref,
                        "label": nodes[ref]["label"] if ref in nodes else ref,
                        "kind": nodes[ref]["kind"] if ref in nodes else "unknown",
                    }
                    for ref in path.refs
                ],
                "edgeKinds": path.edge_kinds,
            }
        )
    return {"paths": paths, "reachable": len(paths) > 0}


_ = asyncio, MAX_PATHS
