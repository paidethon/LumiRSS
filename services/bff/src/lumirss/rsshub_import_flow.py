"""R18 — OPML 导入的 RSSHub 匹配 / 验证 / 替换流（plan → apply）。

流程与安全边界：

- **plan（严格只读）**：解析 OPML → ``rsshub_match.match_source`` 产
  候选与自动建议。不触网、不订阅、不写库。RSSHub 未配置时照常给
  出匹配结果但如实标注 ``rsshubConfigured=false``（apply 会拒绝）。
- **apply（受控变更）**：对每个替换项**先实际验证**——从运营者自己
  的 RSSHub 实例拉取该路由 URL（``RssHubService.fetch_document``：
  origin 锁定 + 有界 body + 共享客户端超时）并确认 200 + 可解析
  feed——再经 FreshRSS 控制适配器**实际订阅**入库（订阅失败 = 稳定
  错误，绝不静默）。有界验证预算（MAX_VALIDATIONS），超预算的项
  如实跳过，不做无界扇出。
- **条目状态诚实边界**：FreshRSS 条目 id 内嵌 feed 地址，已读/收藏/
  批注状态无法跨源安全迁移。因此原 URL 已订阅时**绝不自动退订旧
  源**（keptOldSource=true，报告说明）；新导入项的原始地址记录在
  映射台账（``rsshub_source_mapping``）里，可在来源运维中撤销回原生。
- **凭据不静默替换**：curated 依赖标注为需要凭据的路由
  （``MatchCandidate.needs_credentials``）只进人工选择，绝不自动替换。
- **合并语义不变**：flat 导入的 merge-only（不删、不覆盖既有订阅）
  在本流中原样成立；「替换」是**新增** RSSHub 源 + 台账关联，不是
  改写或删除任何既有订阅。
"""

from lumirss.adapters.freshrss import (
    CATEGORY_PREFIX,
    RESERVED_CATEGORY_LABEL,
    AdapterError,
)
from lumirss.feed_preview import NotAFeedError, parse_feed_document
from lumirss.opml import ParsedOpml
from lumirss.rsshub import (
    RssHubFetchError,
    RssHubNotConfigured,
    RssHubService,
)
from lumirss.rsshub_match import (
    MatchOutcome,
    MissingRouteParams,
    UnsafeRoutePath,
    instantiate_route,
    match_source,
)

__all__ = [
    "STRATEGIES",
    "MAX_VALIDATIONS",
    "RsshubImportService",
    "strategy_or_none",
]

STRATEGIES = ("prefer_rsshub", "prefer_native", "manual")

# 每次 apply 的实际验证预算（每个验证 = 一次到本站 RSSHub 的有界拉取）。
MAX_VALIDATIONS = 30


def strategy_or_none(value: str | None) -> str | None:
    """查询参数策略 → 规范值；缺省 = prefer_rsshub；非法 → None（400）。"""
    if value is None or value.strip() == "":
        return "prefer_rsshub"
    clean = value.strip()
    return clean if clean in STRATEGIES else None


class RsshubImportService:
    """Plan（只读）+ apply（验证后订阅 + 台账）。

    ``control``：FreshRSS 控制适配器（订阅写入）；``rsshub``：
    RssHubService（origin 锁定的实例拉取）；``db``：Lumi 每用户库
    （映射台账；plan 路径允许 None——零写入）。
    """

    def __init__(self, control, rsshub: RssHubService, db=None) -> None:
        self._control = control
        self._rsshub = rsshub
        self._db = db

    # ---- 配置视图 ---------------------------------------------------------

    def _instance_origins(self) -> tuple[str, ...]:
        """本站 RSSHub 的两个可达视角（FreshRSS / BFF），去重保序。

        只取 origin 用于 self/external 分类——绝不让配置 URL 本身
        泄漏到响应里。"""
        from lumirss.http_fetch import origin_of

        try:
            settings = self._rsshub.load_settings()
        except RssHubNotConfigured:
            return ()
        origins: list[str] = []
        for base in (settings.freshrss_base_url, settings.RSSHUB_BASE_URL):
            origin = origin_of(base)
            if origin and origin.lower() not in origins:
                origins.append(origin.lower())
        return tuple(origins)

    # ---- plan（严格只读） ---------------------------------------------------

    def plan(self, parsed: ParsedOpml) -> dict[str, object]:
        """匹配 + 建议（零网络零写入）。"""
        origins = self._instance_origins()
        items: list[dict[str, object]] = []
        counts: dict[str, int] = {}
        for index, entry in enumerate(parsed.entries):
            outcome = match_source(entry.feed_url, entry.html_url, origins)
            decision, note = _decide(outcome)
            counts[decision] = counts.get(decision, 0) + 1
            items.append(
                {
                    "index": index,
                    "title": entry.title,
                    "xmlUrl": entry.feed_url,
                    "htmlUrl": entry.html_url,
                    "category": entry.category_label,
                    "decision": decision,
                    "chosenRoutePath": outcome.auto_route_path,
                    "note": note or outcome.note,
                    "match": outcome.to_dict(),
                }
            )
        return {
            "rsshubConfigured": bool(origins),
            "totalFeeds": len(parsed.entries),
            "fileDuplicates": parsed.duplicate_count,
            "invalidEntries": parsed.invalid_entries,
            "counts": counts,
            "items": items,
        }

    # ---- apply（验证 + 订阅 + 台账） ----------------------------------------

    async def apply(
        self,
        parsed: ParsedOpml,
        *,
        strategy: str,
        approved_indexes: set[int] | None,
        chosen_map: dict[int, str] | None = None,
    ) -> dict[str, object]:
        """执行导入。原 URL 已订阅 → 永不改动（保留旧源 + 关联新源）。

        ``approved_indexes``（manual 策略）：允许替换的预览 index 集合；
        ``chosen_map``（manual 策略可选）：index → 计划内的候选路由路径
        （不在计划内的路径一律拒绝）。"""
        subscriptions = await self._control.list_subscriptions()
        existing_urls = {subscription.feed_url for subscription in subscriptions}
        label_to_id: dict[str, str] = {}
        for category in await self._control.list_categories():
            label_to_id.setdefault(category.label, category.id)

        ctx = _ApplyContext(
            control=self._control,
            rsshub=self._rsshub,
            db=self._db,
            freshrss_base=self._freshrss_view_base(),
            existing_urls=existing_urls,
            label_to_id=label_to_id,
            strategy=strategy,
        )
        chosen_map = chosen_map or {}

        replaced: list[dict[str, object]] = []
        added_native: list[dict[str, object]] = []
        skipped: list[dict[str, str]] = []
        failed: list[dict[str, str]] = []
        mappings: list[dict[str, object]] = []
        kept_old: list[dict[str, str]] = []

        for index, entry in enumerate(parsed.entries):
            outcome = match_source(entry.feed_url, entry.html_url, ctx.origins)
            want_replace = _wants_replace(outcome, strategy, approved_indexes, index)

            if want_replace:
                item, validation_used = await ctx.replace_entry(
                    entry, outcome, override_path=chosen_map.get(index)
                )
                if validation_used:
                    ctx.validations_left -= 1
                decision = str(item.get("decision", ""))
                if decision == "replaced":
                    replaced.append(item)
                    if item.get("keptOldSource"):
                        kept_old.append(
                            {
                                "originalUrl": str(item["originalUrl"]),
                                "rsshubUrl": str(item["rsshubUrl"]),
                            }
                        )
                    mapping = item.get("mapping")
                    if isinstance(mapping, dict):
                        mappings.append(mapping)
                elif decision == "native_fallback":
                    item.pop("decision", None)
                    added_native.append(item)
                elif decision == "skipped":
                    skipped.append(
                        {
                            "feedUrl": str(item["originalUrl"]),
                            "title": str(item["title"]),
                            "reason": str(item.get("reason") or "skipped"),
                        }
                    )
                    # 替换未发生（预算耗尽 / 路由不可构造 / 计划外路径 /
                    # 已订阅）：原始地址照常按原生合并导入——跳过的是
                    # 「替换」，不是「导入」。
                    if str(item["originalUrl"]) not in ctx.existing_urls:
                        native = await ctx.subscribe_native(entry)
                        if str(native.get("decision")) == "failed":
                            failed.append(
                                {
                                    "feedUrl": str(item["originalUrl"]),
                                    "title": str(item["title"]),
                                    "error": str(native.get("error") or "failed"),
                                }
                            )
                        else:
                            native.pop("decision", None)
                            added_native.append(native)
                else:  # failed（验证失败且策略不允许回落 / FreshRSS 拒绝）
                    failed.append(
                        {
                            "feedUrl": str(item["originalUrl"]),
                            "title": str(item["title"]),
                            "error": str(
                                item.get("reason") or item.get("error") or "failed"
                            ),
                        }
                    )
                continue

            # 不替换 → 原生合并导入（与 flat 语义一致；已订阅 = duplicate）
            if entry.feed_url in ctx.existing_urls:
                skipped.append(
                    {
                        "feedUrl": entry.feed_url,
                        "title": entry.title or entry.feed_url,
                        "reason": "duplicate",
                    }
                )
                continue
            item = await ctx.subscribe_native(entry)
            added_native.append(item)

        return {
            "strategy": strategy,
            "replaced": replaced,
            "addedNative": added_native,
            "keptOldSource": kept_old,
            "skipped": skipped,
            "failed": failed,
            "mappings": mappings,
            "counts": {
                "replaced": len(replaced),
                "addedNative": len(added_native),
                "keptOldSource": len(kept_old),
                "skipped": len(skipped),
                "failed": len(failed),
            },
            "entryStateNote": (
                "FreshRSS 已读/收藏/批注状态绑定条目地址，无法跨源安全迁移："
                "原地址已订阅的来源保留旧源并关联新源（绝不自动退订）；"
                "新导入来源的原始地址记录在映射中，可撤销回原生。"
            ),
        }

    def _freshrss_view_base(self) -> str:
        """订阅地址使用的实例视角（FreshRSS 容器可达 base）。"""
        settings = self._rsshub.load_settings()
        return settings.freshrss_base_url


def _decide(outcome: MatchOutcome) -> tuple[str, str | None]:
    """MatchOutcome → plan decision（与 apply 的执行分支一致）。"""
    if outcome.kind == "self_rsshub":
        return "alreadyRsshub", None
    if outcome.kind == "external_rsshub":
        return "autoReplace", None
    if outcome.kind == "unknown":
        return "keepNative", outcome.note
    # native：唯一可自动的安全候选才 auto_replace
    if outcome.auto_route_path is not None:
        return "autoReplace", None
    high = [c for c in outcome.candidates if c.confidence == "high"]
    if high and high[0].needs_credentials:
        return "needsCredentials", outcome.note
    if high and high[0].missing_params:
        return "needsParams", outcome.note
    if outcome.candidates:
        return "manualChoice", outcome.note
    return "keepNative", outcome.note


def _wants_replace(
    outcome: MatchOutcome, strategy: str, approved: set[int] | None, index: int
) -> bool:
    if strategy == "prefer_native":
        return False
    if strategy == "manual":
        return approved is not None and index in approved and bool(outcome.candidates)
    # prefer_rsshub：唯一安全建议才自动；外部实例改本站也算
    if outcome.kind == "external_rsshub":
        return True
    return outcome.auto_route_path is not None


def _chosen(
    outcome: MatchOutcome, override_path: str | None = None
) -> tuple[str | None, dict[str, str], object]:
    """替换目标：auto 建议（或外部实例的具名路径）+ 参数 + 候选元数据。

    manual 策略允许 ``override_path`` 显式指定计划中的某条候选路由；
    不在计划候选列表内的路径一律拒绝（规则数据只来自 vendored 快照，
    客户端不能注入任意路径）。"""
    if override_path is not None:
        for candidate in outcome.candidates:
            if candidate.route_path == override_path:
                return override_path, dict(candidate.params), candidate
        return None, {}, None
    if outcome.auto_route_path is None:
        return None, {}, None
    target = outcome.auto_route_path
    if outcome.kind == "external_rsshub":
        candidate = outcome.candidates[0] if outcome.candidates else None
        return target, {}, candidate
    for candidate in outcome.candidates:
        if candidate.route_path == target:
            return target, dict(candidate.params), candidate
    return target, {}, None


def _failure_type(exc: AdapterError) -> str:
    from lumirss.adapters.freshrss import (
        AuthenticationError,
        UpstreamConnectionError,
    )
    from lumirss.adapters.freshrss_control import FeedRejectedError

    if isinstance(exc, FeedRejectedError):
        return "feed_rejected"
    if isinstance(exc, UpstreamConnectionError):
        return "connection_error"
    if isinstance(exc, AuthenticationError):
        return "authentication_error"
    return "upstream_error"


async def _validate(concrete_path: str, rsshub: RssHubService) -> str | None:
    """实际验证：从本站实例拉取该路由 → 200 + 可解析 feed。

    返回 None = 通过；否则返回稳定失败码（不透传上游原文）。"""
    try:
        body = await rsshub.fetch_document(concrete_path)
    except RssHubFetchError as exc:
        return f"rsshub_{exc.failure_class}"
    except RssHubNotConfigured:
        return "rsshub_not_configured"
    try:
        parse_feed_document(body)
    except NotAFeedError:
        return "rsshub_not_a_feed"
    return None


class _ApplyContext:
    """单次 apply 的共享状态（existing 集合 / 分类表 / 验证预算）。"""

    def __init__(
        self,
        *,
        control,
        rsshub: RssHubService,
        db,
        freshrss_base: str,
        existing_urls: set[str],
        label_to_id: dict[str, str],
        strategy: str,
    ) -> None:

        self.control = control
        self.rsshub = rsshub
        self.db = db
        self.freshrss_base = freshrss_base
        self.existing_urls = existing_urls
        self.label_to_id = label_to_id
        self.strategy = strategy
        self.validations_left = MAX_VALIDATIONS
        self.origins = self._origins(rsshub)

    @staticmethod
    def _origins(rsshub: RssHubService) -> tuple[str, ...]:
        from lumirss.http_fetch import origin_of

        try:
            settings = rsshub.load_settings()
        except RssHubNotConfigured:
            return ()
        origins: list[str] = []
        for base in (settings.freshrss_base_url, settings.RSSHUB_BASE_URL):
            origin = origin_of(base)
            if origin and origin.lower() not in origins:
                origins.append(origin.lower())
        return tuple(origins)

    async def replace_entry(
        self, entry, outcome: MatchOutcome, *, override_path: str | None = None
    ) -> tuple[dict[str, object], bool]:
        """执行一个替换项；返回 (结果 item, 是否消耗了验证次数)。"""
        from lumirss.rsshub_source_mapping import RsshubSourceMappingStore

        item: dict[str, object] = {
            "originalUrl": entry.feed_url,
            "title": entry.title or entry.feed_url,
            "keptOldSource": entry.feed_url in self.existing_urls,
        }
        route_path, params, candidate = _chosen(outcome, override_path)
        if route_path is None or candidate is None:
            item["decision"] = "skipped"
            item["reason"] = (
                "route_not_in_plan" if override_path is not None else "no_candidate"
            )
            return item, False
        if self.validations_left <= 0:
            item["decision"] = "skipped"
            item["reason"] = "validation_budget_exhausted"
            return item, False
        try:
            concrete = instantiate_route(route_path, params)
        except (MissingRouteParams, UnsafeRoutePath) as exc:
            item["decision"] = "skipped"
            item["reason"] = "route_not_constructable"
            item["note"] = str(exc)
            return item, False
        rsshub_url = f"{self.freshrss_base}{concrete}"
        if rsshub_url in self.existing_urls:
            item["decision"] = "skipped"
            item["reason"] = "rsshub_already_subscribed"
            item["rsshubUrl"] = rsshub_url
            return item, False
        failure = await _validate(concrete, self.rsshub)
        if failure is not None:
            item["rsshubUrl"] = rsshub_url
            # 优先已验证 RSSHub：验证失败时，新导入项回落原生（如实报告）；
            # 保留旧源的项无「回落」可言（旧源仍在订阅中），按失败上报。
            if (
                failure.startswith("rsshub_")
                and self.strategy == "prefer_rsshub"
                and not item["keptOldSource"]
            ):
                native = await self.subscribe_native(entry)
                if str(native.get("decision")) == "failed":
                    item["decision"] = "failed"
                    item["reason"] = str(native.get("error") or failure)
                else:
                    item["decision"] = "native_fallback"
                    item["reason"] = failure
                return item, True
            item["decision"] = "failed"
            item["reason"] = failure
            return item, True
        try:
            subscription = await self.control.subscribe(
                rsshub_url, title=entry.title or None
            )
        except AdapterError as exc:
            item["decision"] = "failed"
            item["reason"] = "freshrss_rejected"
            item["error"] = _failure_type(exc)
            item["rsshubUrl"] = rsshub_url
            return item, True
        self.existing_urls.add(rsshub_url)
        await place_category(
            self.control, subscription.stream_id, entry.category_label, self.label_to_id
        )
        mapping = None
        if self.db is not None:
            mapping = await RsshubSourceMappingStore(self.db).record(
                original_url=entry.feed_url,
                rsshub_url=rsshub_url,
                namespace=candidate.namespace,
                route_path=concrete,
                strategy=self.strategy,
                kept_old_source=bool(item["keptOldSource"]),
            )
        item["decision"] = "replaced"
        item["rsshubUrl"] = rsshub_url
        item["validated"] = True
        if mapping is not None:
            item["mapping"] = mapping
        return item, True

    async def subscribe_native(self, entry) -> dict[str, object]:
        """原生合并导入（与 flat 导入同语义）。"""
        try:
            subscription = await self.control.subscribe(
                entry.feed_url, title=entry.title or None
            )
        except AdapterError as exc:
            return {
                "originalUrl": entry.feed_url,
                "title": entry.title or entry.feed_url,
                "decision": "failed",
                "reason": "freshrss_rejected",
                "error": _failure_type(exc),
            }
        self.existing_urls.add(entry.feed_url)
        applied = await place_category(
            self.control, subscription.stream_id, entry.category_label, self.label_to_id
        )
        return {
            "originalUrl": entry.feed_url,
            "title": subscription.title,
            "categoryLabel": (entry.category_label or "").strip() or None,
            "categoryApplied": applied,
        }


async def place_category(
    control, stream_id: str, label: str | None, label_to_id: dict[str, str]
) -> bool:
    """与 flat 导入同语义的分类放置（失败不回滚订阅，返回 applied）。"""
    clean = (label or "").strip()
    if not clean or clean == RESERVED_CATEGORY_LABEL:
        return False
    try:
        target_id = label_to_id.get(clean)
        if target_id is None:
            await control.move_to_new_category(stream_id, clean)
            label_to_id[clean] = f"{CATEGORY_PREFIX}{clean}"
        else:
            await control.move_category(stream_id, target_id)
        return True
    except AdapterError:
        return False
