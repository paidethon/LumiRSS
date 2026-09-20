"""token_backfill — §13.4 存量明文凭据的启动时一次性哈希回填。

SQL 里做不了 sha256（SQLite 无内建），所以迁移 0066 只加标记列；本模块
在服务端启动（lifespan）对四个表列执行 Python 逐行原地哈希：

- 只处理 ``*_is_hash = 0`` 的行（旧明文）；已是哈希形状的值直接置标记
  跳过重算（幂等——重复启动零写入）；
- ``rowid`` 定位单行 UPDATE（四条内联 UPDATE 站点，每表一条）；
- gpt_digest feed token 在 secrets.json（非 SQLite）：同形状判定幂等
  升级，见 :func:`upgrade_digest_feed_token`。

回填前后校验都经 :func:`lumirss.token_hash.verify_token`——回填前窗口
走旧明文兼容分支，回填后走哈希比对；旧链接/旧 bearer 永不失效。
"""

import logging

from lumirss.secrets_store import SecretsStore
from lumirss.storage import Database
from lumirss.token_hash import hash_token, is_token_hash

_logger = logging.getLogger(__name__)

DIGEST_FEED_TOKEN_KEY = "gpt_digest_feed_token"


async def backfill_token_hashes(db: Database) -> dict[str, int]:
    """四个表列的原地哈希回填；返回各表实际改写的行数（诚实计数）。"""
    await db.migrate()
    counts: dict[str, int] = {}

    # mail_bridge_lists.secret
    rows = await db.fetch_all(
        "SELECT rowid, secret FROM mail_bridge_lists WHERE secret_is_hash = 0"
    )
    changed = 0
    for row in rows:
        value = str(row["secret"] or "")
        if value == "" or is_token_hash(value):
            continue
        await db.execute(
            "UPDATE mail_bridge_lists SET secret = ?, secret_is_hash = 1 WHERE rowid = ?",
            (hash_token(value), row["rowid"]),
        )
        changed += 1
    counts["mail_bridge_lists"] = changed

    # inbox_sources.secret
    rows = await db.fetch_all(
        "SELECT rowid, secret FROM inbox_sources WHERE secret_is_hash = 0"
    )
    changed = 0
    for row in rows:
        value = str(row["secret"] or "")
        if value == "" or is_token_hash(value):
            continue
        await db.execute(
            "UPDATE inbox_sources SET secret = ?, secret_is_hash = 1 WHERE rowid = ?",
            (hash_token(value), row["rowid"]),
        )
        changed += 1
    counts["inbox_sources"] = changed

    # saved_searches.feed_secret
    rows = await db.fetch_all(
        "SELECT rowid, feed_secret FROM saved_searches WHERE feed_secret_is_hash = 0"
    )
    changed = 0
    for row in rows:
        value = str(row["feed_secret"] or "")
        if value == "" or is_token_hash(value):
            continue
        await db.execute(
            "UPDATE saved_searches SET feed_secret = ?, feed_secret_is_hash = 1 WHERE rowid = ?",
            (hash_token(value), row["rowid"]),
        )
        changed += 1
    counts["saved_searches"] = changed

    # api_sources.secret
    rows = await db.fetch_all(
        "SELECT rowid, secret FROM api_sources WHERE secret_is_hash = 0"
    )
    changed = 0
    for row in rows:
        value = str(row["secret"] or "")
        if value == "" or is_token_hash(value):
            continue
        await db.execute(
            "UPDATE api_sources SET secret = ?, secret_is_hash = 1 WHERE rowid = ?",
            (hash_token(value), row["rowid"]),
        )
        changed += 1
    counts["api_sources"] = changed

    return counts


def upgrade_digest_feed_token(secrets: SecretsStore) -> bool:
    """gpt_digest feed token（secrets.json 单键）哈希升级。

    幂等：已是哈希形状 → 不写。返回是否发生改写。旧链接兼容与四表同
    理由：校验走 verify_token，升级只把静态明文换成静态哈希。"""
    current = secrets.get(DIGEST_FEED_TOKEN_KEY)
    if not current or is_token_hash(current):
        return False
    secrets.set(DIGEST_FEED_TOKEN_KEY, hash_token(current))
    return True
