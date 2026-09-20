"""F028 术语表批量导入导出 —— 两种模式、超限、roundtrip 幂等、CJK。"""

import json


def _import(client, terms, mode="skip"):
    return client.post("/api/v1/glossary/import", json={"terms": terms, "mode": mode})


def test_f028_import_modes_bounds_and_errors(client):
    # 正常导入（含 CJK）
    first = _import(client, [
        {"term": "LLM", "translation": "大语言模型"},
        {"term": "检索增强生成", "translation": "RAG：先检索后生成的技术"},
        {"term": "MoE", "translation": "Mixture of Experts"},
    ])
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["imported"] == 3
    assert body["skipped"] == 0 and body["overwritten"] == 0

    # skip：重复 term 跳过
    again = _import(client, [{"term": "LLM", "translation": "另一个解释"}])
    assert again.json()["imported"] == 0
    assert again.json()["skipped"] == 1

    # overwrite：重复 term 覆盖
    over = _import(client, [{"term": "LLM", "translation": "Large Language Model"}], mode="overwrite")
    assert over.json()["overwritten"] == 1
    listing = client.get("/api/v1/glossary", params={"q": "LLM"}).json()["items"]
    assert any(item["definition"] == "Large Language Model" for item in listing)

    # 非法结构逐条 error，其余照常导入（不整体失败）
    mixed = _import(client, [
        {"term": "好词条", "translation": "解释"},
        {"term": "", "translation": "空词条"},
        {"term": "缺字段"},
        "not-an-object",
        {"term": "长".join(["x"] * 60), "translation": "超长 term"},
    ])
    assert mixed.status_code == 200
    mixed_body = mixed.json()
    assert mixed_body["imported"] == 1
    assert len(mixed_body["errors"]) == 4
    assert all("index" in err for err in mixed_body["errors"])

    # 超批上限 → 422
    too_many = _import(client, [
        {"term": f"t{i}", "translation": "v"} for i in range(501)
    ])
    assert too_many.status_code == 422


def test_f028_export_roundtrip_idempotent(client):
    _import(client, [
        {"term": "术语甲", "translation": "解释甲"},
        {"term": "术语乙", "translation": "解释乙"},
    ])
    exported = client.get("/api/v1/glossary/export")
    assert exported.status_code == 200
    assert exported.headers["content-type"].startswith("application/json")
    assert "attachment" in exported.headers.get("content-disposition", "")
    payload = json.loads(exported.content.decode("utf-8"))
    terms = {item["term"]: item["translation"] for item in payload["terms"]}
    assert terms["术语甲"] == "解释甲" and terms["术语乙"] == "解释乙"

    # roundtrip：导出 → skip 导入 → 全部 skipped（幂等）
    roundtrip = _import(client, payload["terms"], mode="skip")
    assert roundtrip.status_code == 200
    body = roundtrip.json()
    assert body["imported"] == 0 and body["overwritten"] == 0
    assert body["skipped"] == len(payload["terms"])
