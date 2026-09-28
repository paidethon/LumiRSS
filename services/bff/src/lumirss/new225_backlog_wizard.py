"""NEW-225 积压处理向导 —— 长时间未读范围的「抽样预览 → 显式处置」。

r3 F024/N049 积压助手（两段式批量已读 + 撤销台账）的延伸：向导把
「决定权」摆到台前——范围按来源抽样预览后，用户对每个来源显式选择：

- ``keep``     保留未读：写入 backlog_keep_decisions 台账（来源+范围
               粒度唯一锚点），后续同范围预览排除已「审过保留」的来源；
- ``archive``  归档（置读）：完全复用 N049 批次管线（真实 COUNT 预览
               → 30s token → 逐条 set-read 管线 → 撤销台账），**绝不
               默认全标已读**——没有 token 的 apply 一律 409；
- ``stage``    分批阅读：把该来源未读样本（≤10 条）加入 NEW-221 时段
               （时段由用户指定；没有指定时段的 stage 一律 422）。

服务端没有任何「跳过预览直接处置」的路径。
"""

import hmac
from datetime import UTC, datetime, timedelta
from typing import Any

from lumirss.backlog import (
    _EFFECTIVE_EXCLUSIONS,
    BacklogConflict,
    backlog_batch_rows,
    backlog_batches,
    issue_preview_token,
    record_batch_log,
    validate_apply_token,
)
from lumirss.new221_time_slots import (
    SlotInvalid,
    SlotItemConflict,
    SlotNotFound,
    TimeSlotStore,
)
from lumirss.storage import Database
from lumirss.util import utc_now

_MIN_DAYS = 7
_MAX_DAYS = 365
_MAX_GROUPS = 50
_SAMPLE_PER_SOURCE = 3
_STAGE_CAP = 10


class WizardInvalid(Exception):
    """向导载荷非法（范围/来源/决策）——422 invalid_backlog_wizard。"""


class WizardConflict(Exception):
    """预演 token 缺失/过期/条件漂移——409 backlog_wizard_conflict。"""


def validate_days(older_than_days: int) -> int:
    if not isinstance(older_than_days, int) or isinstance(older_than_days, bool):
        raise WizardInvalid("olderThanDays 必须是整数。")
    if not _MIN_DAYS <= older_than_days <= _MAX_DAYS:
        raise WizardInvalid(f"olderThanDays 必须在 {_MIN_DAYS}..{_MAX_DAYS} 之间。")
    return older_than_days


class BacklogWizardStore:
    """Range preview + explicit dispositions (keep / archive / stage)."""

    def __init__(self, db: Database) -> None:
        self._db = db

    # -- preview ----------------------------------------------------------------

    async def preview(self, older_than_days: int) -> dict[str, Any]:
        """按来源分组的长积压预览：真实 COUNT + 每来源抽样标题。

        候选口径与 N049 完全同一（backlog_rows：未读 + 未加星 + 不在
        稍后读工作区 + 账龄下限）；已「审过保留」（backlog_keep_decisions
        同范围）的来源排除，keptDecisionsExcluded 诚实标注排除量。"""
        await self._db.migrate()
        days = validate_days(older_than_days)
        batches = [
            batch
            for batch in await backlog_batches(
                self._db,
                group_by="source",
                older_than_days=days,
                feed_url=None,
                category_id=None,
            )
            if batch["key"]
        ]
        kept = await self._db.fetch_all(
            "SELECT feed_url FROM backlog_keep_decisions WHERE older_than_days = ?",
            (days,),
        )
        kept_urls = {str(row["feed_url"]) for row in kept}
        visible = [batch for batch in batches if batch["key"] not in kept_urls]
        visible.sort(key=lambda batch: (-batch["count"], batch["key"]))
        truncated = len(visible) > _MAX_GROUPS
        groups = []
        for batch in visible[:_MAX_GROUPS]:
            feed_url = batch["key"]
            meta = await self._feed_meta(feed_url, batch["entryRefs"])
            groups.append(
                {
                    "feedUrl": feed_url,
                    "feedTitle": meta["feedTitle"],
                    "unreadCount": batch["count"],
                    "sample": meta["sample"],
                    "oldest": meta["oldest"],
                }
            )
        return {
            "olderThanDays": days,
            "cutoff": self._cutoff(days),
            "groups": groups,
            "truncated": truncated,
            "keptDecisionsExcluded": len(batches) - len(visible),
            "effectiveExclusions": list(_EFFECTIVE_EXCLUSIONS),
        }

    async def _feed_meta(self, feed_url: str, refs: list[str]) -> dict[str, Any]:
        """来源标题 + 抽样条目标题（≤3，诚实有界）。"""
        feed_title_row = await self._db.fetch_one(
            "SELECT feed_title FROM search_feeds WHERE feed_url = ?", (feed_url,)
        )
        sample: list[dict[str, Any]] = []
        oldest = None
        if refs:
            bare_refs = [ref.removeprefix("rss:") for ref in refs]
            placeholders = ",".join("?" for _ in bare_refs)
            rows = await self._db.fetch_all(
                "SELECT title, published_at FROM search_entries"
                f" WHERE entry_ref IN ({placeholders})"
                " ORDER BY published_at ASC",
                tuple(bare_refs),
            )
            sample = [{"title": str(row["title"])} for row in rows[:_SAMPLE_PER_SOURCE]]
            oldest = str(rows[0]["published_at"]) if rows else None
        return {
            "feedTitle": feed_title_row["feed_title"] if feed_title_row else feed_url,
            "sample": sample,
            "oldest": oldest,
        }

    @staticmethod
    def _cutoff(days: int) -> str:
        moment = datetime.now(UTC) - timedelta(days=days)
        return moment.strftime("%Y-%m-%dT%H:%M:%SZ")

    # -- keep -------------------------------------------------------------------

    async def keep(self, feed_url: str, older_than_days: int, note: str | None) -> dict[str, Any]:
        """「这次审过、决定保留未读」台账（幂等 upsert）。"""
        await self._db.migrate()
        days = validate_days(older_than_days)
        if not isinstance(feed_url, str) or not feed_url.strip():
            raise WizardInvalid("feedUrl 必须是非空字符串。")
        feed_url = feed_url.strip()
        existing = await self._db.fetch_one(
            "SELECT id FROM backlog_keep_decisions"
            " WHERE feed_url = ? AND older_than_days = ?",
            (feed_url, days),
        )
        clean_note = (note or "").strip() or None
        if existing is not None:
            if clean_note is None:
                # 重复 keep 未带 note：保留原批注（last-wins 只对显式内容）。
                prior = await self._db.fetch_one(
                    "SELECT note FROM backlog_keep_decisions WHERE id = ?",
                    (str(existing["id"]),),
                )
                clean_note = prior["note"] if prior else None
            await self._db.execute(
                "UPDATE backlog_keep_decisions SET decided_at = ?, note = ?"
                " WHERE id = ?",
                (utc_now(), clean_note, str(existing["id"])),
            )
        else:
            await self._db.execute(
                "INSERT INTO backlog_keep_decisions (id, feed_url, older_than_days,"
                " decided_at, note) VALUES (?, ?, ?, ?, ?)",
                (
                    f"bkeep-{hmac.new(feed_url.encode(), str(days).encode(), 'sha256').hexdigest()[:24]}",
                    feed_url,
                    days,
                    utc_now(),
                    clean_note,
                ),
            )
        return {
            "feedUrl": feed_url,
            "olderThanDays": days,
            "note": clean_note,
            "decidedAt": utc_now(),
            "outcome": "kept",
        }

    async def list_keep_decisions(self) -> dict[str, Any]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT id, feed_url, older_than_days, decided_at, note"
            " FROM backlog_keep_decisions ORDER BY decided_at DESC"
        )
        return {
            "items": [
                {
                    "id": str(row["id"]),
                    "feedUrl": str(row["feed_url"]),
                    "olderThanDays": int(row["older_than_days"]),
                    "decidedAt": str(row["decided_at"]),
                    "note": row["note"],
                }
                for row in rows
            ]
        }

    # -- archive（复用 N049 批次管线） --------------------------------------------

    async def archive_preview(
        self, feed_url: str, older_than_days: int
    ) -> dict[str, Any]:
        """归档预演：真实 COUNT + 30s 一次性 token（进 apply 必带）。"""
        await self._db.migrate()
        days = validate_days(older_than_days)
        if not isinstance(feed_url, str) or not feed_url.strip():
            raise WizardInvalid("feedUrl 必须是非空字符串。")
        rows = await backlog_batch_rows(
            self._db,
            group_by="source",
            batch_key=feed_url.strip(),
            older_than_days=days,
            feed_url=None,
            category_id=None,
            limit=None,
        )
        condition = {
            "kind": "backlog_wizard_archive",
            "groupBy": "source",
            "key": feed_url.strip(),
            "olderThanDays": days,
        }
        return {
            "feedUrl": feed_url.strip(),
            "olderThanDays": days,
            "count": len(rows),
            "sample": [
                {"entryRef": str(row["entry_ref"]), "title": row["title"]}
                for row in rows[:_SAMPLE_PER_SOURCE]
            ],
            "effectiveExclusions": list(_EFFECTIVE_EXCLUSIONS),
            "confirmToken": issue_preview_token(condition),
            "note": "预演只是数字；确认归档必须携带本 token（30 秒内）。",
        }

    async def archive_apply(
        self,
        feed_url: str,
        older_than_days: int,
        confirm_token: str,
        mark_read,  # async (entry_ref) -> bool — set-read pipeline callback
    ) -> dict[str, Any]:
        """归档执行：token 校验（缺失/漂移 → 409）→ 逐条置读 →
        实际成功的 refs 写入 N049 撤销台账（可撤销）。"""
        days = validate_days(older_than_days)
        if not isinstance(feed_url, str) or not feed_url.strip():
            raise WizardInvalid("feedUrl 必须是非空字符串。")
        feed_url = feed_url.strip()
        condition = {
            "kind": "backlog_wizard_archive",
            "groupBy": "source",
            "key": feed_url,
            "olderThanDays": days,
        }
        try:
            validate_apply_token(confirm_token, condition)
        except BacklogConflict as exc:
            raise WizardConflict(str(exc)) from exc
        rows = await backlog_batch_rows(
            self._db,
            group_by="source",
            batch_key=feed_url,
            older_than_days=days,
            feed_url=None,
            category_id=None,
            limit=_STAGE_CAP * 20,  # 单次归档执行上限（400）：超出的再来一轮
        )
        applied_refs: list[str] = []
        failed = 0
        for row in rows:
            if await mark_read(str(row["entry_ref"])):
                applied_refs.append(str(row["entry_ref"]))
            else:
                failed += 1
        log_id = None
        if applied_refs:
            log_id = await record_batch_log(
                self._db,
                group_by="source",
                batch_key=feed_url,
                refs=applied_refs,
                applied_count=len(applied_refs),
            )
        return {
            "feedUrl": feed_url,
            "olderThanDays": days,
            "applied": len(applied_refs),
            "failed": failed,
            "batchLogId": log_id,
            "undoAvailable": log_id is not None,
        }

    # -- stage（分批阅读 → NEW-221 时段） ----------------------------------------

    async def stage_batches(
        self, feed_url: str, older_than_days: int, slot_id: str | None
    ) -> dict[str, Any]:
        """把该来源未读样本（≤10 条）加入用户指定时段（分批阅读）。

        slot_id 必须由用户显式提供（422 otherwise）；已有时段归属的
        文章跳过（NEW-221 pending 唯一），诚实报告 staged/skipped。"""
        await self._db.migrate()
        days = validate_days(older_than_days)
        if not isinstance(feed_url, str) or not feed_url.strip():
            raise WizardInvalid("feedUrl 必须是非空字符串。")
        if not slot_id:
            raise WizardInvalid(
                "分批阅读需要你先选一个时段（targetSlotId）——服务端不替你挑。"
            )
        slots = TimeSlotStore(self._db)
        try:
            await slots.get_slot_detail(slot_id)
        except SlotNotFound as exc:
            raise WizardInvalid("目标时段不存在。") from exc
        rows = await backlog_batch_rows(
            self._db,
            group_by="source",
            batch_key=feed_url.strip(),
            older_than_days=days,
            feed_url=None,
            category_id=None,
            limit=_STAGE_CAP,
        )
        staged: list[str] = []
        skipped = 0
        for row in rows:
            item_ref = f"rss:{row['entry_ref']}"
            try:
                _row, outcome = await slots.add_item(slot_id, item_ref)
            except SlotItemConflict:
                skipped += 1
                continue
            except SlotInvalid:
                skipped += 1
                continue
            if outcome == "created":
                staged.append(item_ref)
            else:  # duplicate（同一时段已有 pending）→ 如实计 skipped。
                skipped += 1
        return {
            "feedUrl": feed_url.strip(),
            "olderThanDays": days,
            "slotId": slot_id,
            "staged": staged,
            "stagedCount": len(staged),
            "skippedAlreadyInSlot": skipped,
            "note": "分批阅读 = 加入所选时段；后续读不读、何时读仍由你决定。",
        }
