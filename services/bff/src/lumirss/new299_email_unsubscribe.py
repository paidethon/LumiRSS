"""NEW-299 通讯退订信息卡 —— 从原文明确提供的 List-Unsubscribe 等头部
展示退订方式；用户主动打开，不自动执行退订请求。

诚实口径（硬规则）：

- 信息只来自邮件原文头部（List-Unsubscribe / List-Unsubscribe-Post /
  List-Help），系统不猜、不推导、不补全——头部没有 = 没有退订信息
  （404 语义 no_unsubscribe_info，绝不生成猜测的退订地址）；
- 【零网络】：本组端点不存在任何外发请求。One-Click 头
  （List-Unsubscribe=One-Click）只如实展示「原文声明支持一键退订」，
  LumiRSS 绝不代发 POST——用户必须自己在邮件客户端/浏览器完成；
- 「打开」= 用户主动动作：POST unsubscribe-open 只记录这次用户决定
  （审计），不 fetch、不预览、不 ping 目标地址。

per-user：打开记录在 per-user 库，A 的记录对 B 不可见。
"""

import uuid
from typing import Any

from lumirss.storage import Database
from lumirss.util import utc_now

HONESTY_NOTE = (
    "退订信息只来自邮件原文头部；LumiRSS 只展示、绝不自动执行退订请求"
    "（包括 One-Click）——打开与否、何时打开由你决定并在邮件客户端或"
    "浏览器中完成。"
)

_HTTP_SCHEMES = ("http://", "https://")


def parse_unsubscribe_headers(headers: dict[str, str]) -> list[dict[str, str]]:
    """解析 List-Unsubscribe 的 <..> 项为 http / mailto 方法（纯函数）。"""
    raw = str(headers.get("List-Unsubscribe") or "")
    methods: list[dict[str, str]] = []
    for token in raw.split(","):
        token = token.strip().strip("<>").strip()
        if not token:
            continue
        lowered = token.lower()
        if lowered.startswith(_HTTP_SCHEMES):
            methods.append({"type": "http", "target": token})
        elif lowered.startswith("mailto:"):
            methods.append({"type": "mailto", "target": token})
    return methods


class EmailUnsubStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def card(self, material_id: str) -> dict[str, Any] | None:
        """退订信息卡：原文头部如实展示；没有就明说没有。"""
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT headers_json FROM email_materials WHERE id = ?",
            (material_id,),
        )
        if row is None:
            return None
        import json

        headers = json.loads(str(row["headers_json"] or "{}"))
        methods = parse_unsubscribe_headers(headers)
        one_click = "one-click" in str(
            headers.get("List-Unsubscribe-Post") or ""
        ).lower()
        list_help = str(headers.get("List-Help") or "").strip().strip("<>").strip()[:500]
        if not methods and not one_click and not list_help:
            return {
                "materialId": material_id,
                "available": False,
                "methods": [],
                "oneClickDeclared": False,
                "listHelp": "",
                "opens": [],
                "honestyNote": (
                    "这封邮件的原文头部没有提供任何退订信息"
                    "（List-Unsubscribe / List-Help 均缺失）；"
                    "系统不会猜测退订地址。"
                ),
            }
        return {
            "materialId": material_id,
            "available": True,
            "methods": methods,
            "oneClickDeclared": one_click,
            "listHelp": list_help,
            "opens": await self._opens(material_id),
            "honestyNote": HONESTY_NOTE,
        }

    async def _opens(self, material_id: str) -> list[dict[str, Any]]:
        rows = await self._db.fetch_all(
            "SELECT method, target, opened_at FROM email_unsub_opens"
            " WHERE material_id = ? ORDER BY opened_at DESC, id DESC LIMIT 20",
            (material_id,),
        )
        return [dict(r) for r in rows]

    async def record_open(
        self, material_id: str, method: str, target: str
    ) -> dict[str, Any]:
        """记录用户主动打开某条退订途径（审计；无任何网络副作用）。"""
        card = await self.card(material_id)
        if card is None:
            raise LookupError("没有这条邮件资料条目。")
        if not card["available"]:
            raise ValueError("这封邮件没有退订信息可打开。")
        matched = next(
            (m for m in card["methods"] if m["type"] == method and m["target"] == target),
            None,
        )
        if matched is None:
            raise ValueError("要打开的途径不在原文提供的退订信息里。")
        open_id = f"euo-{uuid.uuid4().hex[:20]}"
        await self._db.execute(
            "INSERT INTO email_unsub_opens (id, material_id, method, target,"
            " opened_at) VALUES (?, ?, ?, ?, ?)",
            (open_id, material_id, method, target[:2000], utc_now()),
        )
        return {
            "id": open_id,
            "materialId": material_id,
            "method": method,
            "target": target,
            "openedAt": utc_now(),
            "note": "已记录你主动打开；请求由你自己在客户端完成，LumiRSS 不发送。",
        }
