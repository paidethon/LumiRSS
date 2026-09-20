"""登录限流 XFF 分桶（2026-09-20 安全整改）。

反代（Caddy）后 socket peer 恒为代理地址：修复前所有客户端共享一个
失败桶（5 次/分钟）→ 任意第三方可锁死登录。修复后仅可信代理网段的
peer 采纳 X-Forwarded-For **最后一跳**；不可信 peer 的 XFF 一律忽略。
"""

import importlib

from lumirss import middleware


def _scope(peer: str, xff: str | None = None) -> dict:
    headers = []
    if xff is not None:
        headers.append((b"x-forwarded-for", xff.encode("latin-1")))
    return {"client": (peer, 12345), "headers": headers}


def _reset_buckets() -> None:
    middleware._login_failures.clear()


def test_trusted_proxy_peer_uses_last_xff_hop():
    # Caddy（loopback）转发：XFF "客户端伪造值, 真实客户端" → 取最后一跳
    key = middleware._client_key(_scope("127.0.0.1", "9.9.9.9, 203.0.113.7"))
    assert key == "203.0.113.7"


def test_untrusted_peer_xff_is_ignored():
    # 直连公网 peer 伪造 XFF → 不采纳，桶=peer 自身
    key = middleware._client_key(_scope("198.51.100.9", "1.2.3.4"))
    assert key == "198.51.100.9"


def test_trusted_peer_without_xff_uses_peer():
    assert middleware._client_key(_scope("127.0.0.1", None)) == "127.0.0.1"


def test_private_network_peer_is_trusted_by_default():
    # compose 内 Caddy 网段（172.16/12）
    assert middleware._client_key(_scope("172.18.0.5", "203.0.113.99")) == "203.0.113.99"


def test_failures_from_one_client_do_not_lock_another():
    # 反代场景：A 客户端刷满失败预算不锁 B 客户端（修复前共享桶会被锁死）
    _reset_buckets()
    scope_a = _scope("127.0.0.1", "203.0.113.7")
    scope_b = _scope("127.0.0.1", "203.0.113.8")
    for _ in range(middleware.LOGIN_FAILURE_LIMIT):
        middleware.register_login_failure(scope_a)
    assert not middleware.login_attempts_allowed(scope_a)
    assert middleware.login_attempts_allowed(scope_b)


def test_spoofed_xff_cannot_evade_or_poison_buckets():
    # 不可信 peer 的 XFF 不参与分桶：伪造任意 XFF 都命中同一桶
    _reset_buckets()
    for _ in range(middleware.LOGIN_FAILURE_LIMIT):
        middleware.register_login_failure(_scope("198.51.100.9", f"10.0.0.{_ + 1}"))
    assert not middleware.login_attempts_allowed(_scope("198.51.100.9", "10.9.9.9"))


def test_custom_trusted_networks_env_is_honored(monkeypatch):
    monkeypatch.setenv("LUMIRSS_TRUSTED_PROXY_NETWORKS", "198.51.100.0/24")
    importlib.reload(middleware)
    try:
        # 明确信任的网段采纳 XFF；默认私网不再可信
        assert middleware._client_key(_scope("198.51.100.9", "203.0.113.5")) == "203.0.113.5"
        assert middleware._client_key(_scope("127.0.0.1", "203.0.113.5")) == "127.0.0.1"
    finally:
        monkeypatch.delenv("LUMIRSS_TRUSTED_PROXY_NETWORKS")
        importlib.reload(middleware)
    _reset_buckets()
