"""NEW-331..340 共读空间测试引导（复用 new231_helpers.ab_session）。

owner 创建空间并显式添加成员（一切共享从显式动作开始）；per-user 库
按会话路由；本文件只提炼「建空间 + 添加成员」的重复样板。
"""

from __future__ import annotations

from typing import Any

from new231_helpers import ab_session  # noqa: F401  (re-export 供各测试文件使用)


def make_space(session: Any, owner: dict[str, str], name: str, **payload: Any) -> dict:
    response = session.client.post("/api/v1/spaces", json={"name": name, **payload}, headers=owner)
    assert response.status_code == 201, response.text
    return response.json()


def add_member(
    session: Any, owner: dict[str, str], space_id: str, username: str
) -> dict:
    response = session.client.post(
        f"/api/v1/spaces/{space_id}/members",
        json={"username": username},
        headers=owner,
    )
    assert response.status_code == 201, response.text
    return response.json()


def space_with_members(session: Any, *usernames: str, **payload: Any) -> tuple[dict, list[dict]]:
    """owner 建空间并依次激活 + 添加成员；返回 (space, members)。"""
    space = make_space(session, session.owner, payload.pop("name", "共读空间"), **payload)
    members = []
    for username in usernames:
        session.activate_member(username)
        members.append(add_member(session, session.owner, space["id"], username))
    return space, members
