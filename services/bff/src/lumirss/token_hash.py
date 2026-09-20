"""token_hash — §13.4 安全整改：bearer token 单向验证存储（W6 收口）。

五个 token/secret 落点（mail_bridge_lists.secret / inbox_sources.secret /
saved_searches.feed_secret / api_sources.secret / gpt_digest feed token）
改为只存 SHA-256 hex：库（或 secrets 文件）里不再有明文凭据。校验语义：

- 存储值是哈希（64 位 hex）→ ``compare_digest(stored, sha256(presented))``；
- 存储值是旧明文（回填前/回填失败窗口）→ 退化为原常量时间明文比对——
  旧链接/旧 bearer 永不因升级失效（迁移就是原地把值换成自身哈希）。

哈希不可逆：任何「再次展示」路径（创建/轮换响应之外）都无法再重建
原始凭据——展示语义收敛为一次性（创建/轮换响应带一次明文）。
"""

import hashlib
import hmac

_HEX_DIGITS = frozenset("0123456789abcdef")


def hash_token(token: str) -> str:
    """SHA-256 hex（小写）。输入编码固定 UTF-8。"""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def is_token_hash(value: str) -> bool:
    """形状判定：64 位 hex 即视为已是哈希（32 字节 hex 恰为 64 字符；
    现行 new_*_secret 均为 32/40 hex——不会误判为哈希）。"""
    return len(value) == 64 and all(c in _HEX_DIGITS for c in value)


def verify_token(presented: str | None, stored: str | None) -> bool:
    """单向验证：presented 的哈希与存储值常量时间比对。

    - stored 为哈希 → ``sha256(presented) == stored``；
    - stored 为旧明文 → 常量时间明文比对（升级窗口兼容，永不失效）；
    - 任一侧为空 → False（空凭据不通过）。"""
    if not presented or not stored:
        return False
    presented = str(presented)
    stored = str(stored)
    if is_token_hash(stored):
        return hmac.compare_digest(stored, hash_token(presented))
    return hmac.compare_digest(stored, presented)
