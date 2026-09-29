"""NEW-201..210 组的测试挂载台（不依赖 main.py 路由注册）。

共享装配纪律：功能代码全部在新文件里，main.py / queries.ts 的共享
接线只进最终 wiring commit。因此本组测试用**本地 FastAPI 应用**挂载
被测路由：

- ``app.state.db`` = 真 :class:`RoutingDatabase`（control 路径 +
  users 根都在 pytest tmp_path）——每个请求按 ``x-test-user`` 头
  绑定 user 上下文（缺省 ``owner``），per-user 库路由真实生效；
- FreshRSS 控制适配器按需注入 ``app.state.freshrss_control_adapter``
  （与既有 F004 等套件的 SimpleNamespace 注入同一模式）；不注入且
  被测路由不触网——本组特性零网络依赖；
- 断言走 HTTP 契约（状态码 + 错误信封），与正式挂载后的行为一致。

各测试文件自带 ``make_client`` fixture（挂载各自的 router），保持
文件互相独立、不共享 conftest 改动。
"""

from typing import Any


class _BindTestUser:
    """把 ``x-test-user`` 头（缺省 owner）绑定为请求的 user 上下文。

    只做 user_scope 绑定，不做鉴权——鉴权语义归 main.py 中间件（本组
    测试不覆盖它），per-user 数据隔离由真实 RoutingDatabase 保证。
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        from lumirss.user_scope import user_context

        uid = "owner"
        for key, value in scope.get("headers") or []:
            if key.lower() == b"x-test-user":
                uid = value.decode("latin-1").strip() or "owner"
                break
        with user_context(uid):
            await self.app(scope, receive, send)


def feature_app(tmp_path: Any, *routers: Any):
    """本地应用：真 RoutingDatabase + 被测路由（每个用例独立文件树）。

    TestClient 的生命周期由调用方管理（见各测试文件的 make_client
    fixture）。"""
    from fastapi import FastAPI

    from lumirss.storage import Database
    from lumirss.user_scope import RoutingDatabase

    app = FastAPI()
    for router in routers:
        app.include_router(router)
    control_path = tmp_path / "control.sqlite"
    users_root = tmp_path / "users"
    # 控制库先建好（RoutingDatabase 只在诊断里引用它的路径）。
    Database(control_path)
    app.state.db = RoutingDatabase(control_path, users_root)
    app.add_middleware(_BindTestUser)
    return app
