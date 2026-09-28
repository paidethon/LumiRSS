"""FIX-366: 资源 ID 进出 URL 必须正确往返（中文 / 百分号字符）。

缺陷基线：DELETE /api/v1/authors/aliases/{alias} 对路径参数再 unquote
一次——生产 ASGI 服务器（uvicorn）交付的 scope["path"] 已解码一次，
别名里字面携带 ``%25``（合法转义形状）时被二次解码成另一个名字：
删除请求要么 404，要么命中**同形别名**的记录（跨记录误删）。修复后：
路径参数只解码一次，别名按存储原样匹配；中文与百分号别名完整往返。

测试通道说明：starlette TestClient 自身会把 scope["path"] 二次解码
（httpx ``.path`` 已解码 + testclient 再 unquote），与生产不符；百分号
用例走 httpx ASGITransport（恰好解码一次 = 生产语义），普通用例仍走
TestClient 作回归对照。
"""

import asyncio
from urllib.parse import quote

import httpx
from fastapi.testclient import TestClient

from lumirss.main import app

PERCENT_ALIAS = "转载%25专栏"  # 字面包含合法转义形状 "%25"
LOOKALIKE_ALIAS = "转载%专栏"  # 二次解码会错误命中的名字
CHINESE_ALIAS = "作者张三"


def _alias_path(alias: str) -> str:
    """客户端的正确行为：路径段按 RFC 3986 编码一次。"""
    return "/api/v1/authors/aliases/" + quote(alias, safe="")


def _create_alias(client, alias: str, canonical: str) -> int:
    return client.post(
        "/api/v1/authors/aliases",
        json={"alias": alias, "canonical": canonical},
    ).status_code


def _aliases(client) -> list[str]:
    return [item["alias"] for item in client.get("/api/v1/authors/aliases").json()["items"]]


def _delete_asgi(alias: str) -> int:
    """经 ASGITransport 发 DELETE——scope["path"] 只解码一次（生产语义）。"""

    async def call() -> int:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://asgi-test"
        ) as asgi_client:
            response = await asgi_client.delete(_alias_path(alias))
            return response.status_code

    with TestClient(app):  # lifespan 持有 app.state；请求走同一 app 实例
        return asyncio.run(call())


def test_percent_alias_roundtrip_deletes_the_exact_record():
    with TestClient(app) as client:
        assert _create_alias(client, PERCENT_ALIAS, "张三") == 201
    assert _delete_asgi(PERCENT_ALIAS) == 204
    with TestClient(app) as client:
        assert PERCENT_ALIAS not in _aliases(client)


def test_percent_alias_delete_never_hits_the_lookalike_record():
    """同形别名在场：二次解码会把删除打在「转载%专栏」上——绝不允许。"""
    with TestClient(app) as client:
        assert _create_alias(client, PERCENT_ALIAS, "张三") == 201
        assert _create_alias(client, LOOKALIKE_ALIAS, "李四") == 201

    assert _delete_asgi(PERCENT_ALIAS) == 204

    with TestClient(app) as client:
        remaining = _aliases(client)
    assert PERCENT_ALIAS not in remaining
    assert LOOKALIKE_ALIAS in remaining


def test_chinese_alias_roundtrip(client):
    assert _create_alias(client, CHINESE_ALIAS, "张三") == 201
    response = client.delete(_alias_path(CHINESE_ALIAS))
    assert response.status_code == 204
    assert CHINESE_ALIAS not in _aliases(client)


def test_space_alias_still_roundtrips(client):
    """既有行为回归：普通转义（空格 → %20）别名仍可删除。"""
    assert _create_alias(client, "Zhang San", "张三") == 201
    response = client.delete(_alias_path("Zhang San"))
    assert response.status_code == 204
    assert "Zhang San" not in _aliases(client)


def test_missing_alias_is_still_404(client):
    response = client.delete(_alias_path("不存在的作者"))
    assert response.status_code == 404
