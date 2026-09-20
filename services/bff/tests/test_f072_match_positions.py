"""F072 命中定位 — match_positions 偏移正确性（单测）。"""

from lumirss.search_index import match_positions


def test_match_positions_offsets_and_cap():
    content = "alpha beta alpha gamma alpha"
    terms = ["alpha"]
    positions = match_positions(content, terms, limit=10)
    assert [p["offset"] for p in positions] == [0, 11, 23]
    assert all(p["term"] == "alpha" for p in positions)

    # 上限 10：超出的命中被截断
    many = "hit " * 30
    capped = match_positions(many, ["hit"], limit=10)
    assert len(capped) == 10
    assert capped[0]["offset"] == 0

    # 多 term 合并按偏移排序
    merged = match_positions("b a b a", ["a", "b"], limit=10)
    assert [p["offset"] for p in merged] == [0, 2, 4, 6]

    # casefold 口径与 build_snippet 一致
    assert match_positions("Alpha ALPHA", ["alpha"], limit=10)[0]["offset"] == 0

    # 无命中 → 空表（仅标题命中 → 不启用定位条）
    assert match_positions("没有命中", ["alpha"]) == []


def test_match_positions_dedupes_same_offset():
    # 前缀词命中同一偏移（"a" 与 "ab" 都命中 offset 0）→ 去重
    positions = match_positions("ab ab", ["a", "ab"], limit=10)
    offsets = [p["offset"] for p in positions]
    assert offsets == sorted(offsets)
    assert len(offsets) == len(set(offsets))
