"""RSSHub Control Center (0018) — schema-driven, typed, allow-listed.

Lumi never talks to a Docker socket and never injects arbitrary environment
variables. Instead it owns a **desired config document** (typed allow-list,
stored in lumi.sqlite) and an **applied snapshot** (only updated when the
operator confirms "applied" after restarting RSSHub with the exported config).

- restartRequired(item) = desired != applied. Every editable item requires a
  restart in this RSSHub version (no safe immediate-apply path exists).
- Secrets (ACCESS_KEY, route credentials, PROXY_URI) are write-only via
  SecretsStore and never echoed; changes bump a secretsVersion so the UI can
  honestly show "restart required".
- The schema was verified against the pinned RSSHub image (git 86516b3,
  RSSHub/1.0) by reading its compiled config module inside the running
  container on 2026-09-04. No keys are invented from memory.
"""

import json
import re
import uuid
from dataclasses import dataclass
from typing import Any

from lumirss.secrets_store import SecretsStore
from lumirss.storage import Database
from lumirss.util import utc_now as _utc_now

RSSHUB_CONFIG_SCHEMA_VERSION = 1

DESIRED_KEY = "rsshub.desired"
APPLIED_KEY = "rsshub.applied"

GROUP_LABELS = {
    "instance": "实例",
    "cache": "缓存",
    "network": "网络",
    "access": "访问控制",
    "browser": "浏览器运行时",
    "advanced": "高级",
    "credentials": "路由凭据",
}


class RssHubControlError(Exception):
    """Base class for RSSHub control-center errors (stable API error types)."""


class RssHubUnknownKey(RssHubControlError):
    """A config/secret key outside the typed allow-list (rsshub_unknown_key)."""


class RssHubInvalidValue(RssHubControlError):
    """A value failing type/range validation (rsshub_invalid_value)."""


@dataclass(frozen=True)
class ConfigItem:
    key: str
    label: str
    description: str
    group: str
    type: str  # "int" | "bool" | "string" | "enum" | "secret"
    default: Any
    secret: bool
    editable: bool
    restart_required: bool
    options: tuple[str, ...] | None = None
    minimum: int | None = None
    maximum: int | None = None
    max_length: int | None = None
    source: str = "RSSHub config (pinned image, git 86516b3)"


def _item(
    key: str,
    label: str,
    description: str,
    group: str,
    type_: str,
    default: Any,
    *,
    secret: bool = False,
    editable: bool = True,
    options: tuple[str, ...] | None = None,
    minimum: int | None = None,
    maximum: int | None = None,
    max_length: int | None = None,
) -> ConfigItem:
    return ConfigItem(
        key=key,
        label=label,
        description=description,
        group=group,
        type=type_,
        default=default,
        secret=secret,
        editable=editable,
        restart_required=True,
        options=options,
        minimum=minimum,
        maximum=maximum,
        max_length=max_length,
    )


# The complete allow-list. Anything not declared here can never be persisted.
SCHEMA: tuple[ConfigItem, ...] = (
    # ---- Instance ----
    _item("PORT", "监听端口", "RSSHub 容器内监听端口（信息项，不可在此修改）。", "instance", "int", 1200, editable=False, minimum=1, maximum=65535),
    _item("LISTEN_INADDR_ANY", "监听所有地址", "允许 RSSHub 监听所有网络接口（关闭后仅回环）。", "instance", "bool", True),
    _item("DISABLE_IPV6", "禁用 IPv6", "禁用 IPv6 出站连接。", "instance", "bool", False),
    # ---- Cache ----
    _item("CACHE_TYPE", "缓存类型", "缓存后端：memory（进程内）或 redis。", "cache", "enum", "memory", options=("memory", "redis")),
    _item("CACHE_EXPIRE", "路由缓存过期（分钟）", "路由输出的缓存时间。", "cache", "int", 300, minimum=1, maximum=100000),
    _item("CACHE_CONTENT_EXPIRE", "内容缓存过期（分钟）", "抓取内容的缓存时间。", "cache", "int", 3600, minimum=1, maximum=100000),
    _item("CACHE_REQUEST_TIMEOUT", "缓存请求超时（秒）", "缓存层的请求超时。", "cache", "int", 60, minimum=1, maximum=3600),
    _item("MEMORY_MAX", "内存缓存上限（MB）", "memory 缓存的最大字节数（MB）。", "cache", "int", 256, minimum=16, maximum=65536),
    # ---- Network ----
    _item("REQUEST_TIMEOUT", "请求超时（毫秒）", "上游抓取的请求超时。", "network", "int", 30000, minimum=1000, maximum=300000),
    _item("UA", "User-Agent", "自定义 User-Agent（留空使用默认随机 UA）。", "network", "string", "", max_length=300),
    _item("ALLOW_ORIGIN", "允许的来源", "CORS Allow-Origin 值（留空不设置）。", "network", "string", "", max_length=300),
    _item("DISALLOW_ROBOT", "禁止机器人访问", "在 robots.txt 中声明禁止爬取（DISALLOW_ROBOT）。", "network", "bool", False),
    _item("PROXY_URI", "代理 URI", "上游代理 URI（可能包含认证信息，按秘密处理）。", "network", "string", "", secret=True, max_length=500),
    # ---- Access Control ----
    _item("ACCESS_KEY", "访问密钥", "访问受保护路由所需的密钥（ACCESS_KEY）。", "access", "string", "", secret=True, max_length=300),
    _item("ALLOW_USER_HOTLINK_TEMPLATE", "允许用户自定义防盗链模板", "允许通过查询参数指定防盗链模板。", "access", "bool", False),
    _item("HOTLINK_TEMPLATE", "防盗链模板", "图片防盗链模板。", "access", "string", "", max_length=300),
    _item("ALLOW_USER_SUPPLY_UNSAFE_DOMAIN", "允许用户提供不安全域名", "允许用户提供任意域名（降低安全性，谨慎开启）。", "access", "bool", False),
    # ---- Browser Runtime ----
    _item("PUPPETEER_WS_ENDPOINT", "Puppeteer WS 端点", "远程浏览器 WebSocket 端点。", "browser", "string", "", max_length=500),
    _item("CHROMIUM_EXECUTABLE_PATH", "Chromium 可执行路径", "本地 Chromium 可执行文件路径。", "browser", "string", "", max_length=500),
    _item("ENABLE_REMOTE_DEBUGGING", "启用远程调试", "为浏览器运行时开启远程调试。", "browser", "bool", False),
    # ---- Advanced ----
    _item("DEBUG_INFO", "调试信息", "在错误页暴露调试信息。", "advanced", "bool", True),
    _item("LOGGER_LEVEL", "日志级别", "日志级别（trace/debug/info/warn/error）。", "advanced", "enum", "info", options=("trace", "debug", "info", "warn", "error")),
    _item("NO_LOGFILES", "不写日志文件", "不生成日志文件（仅标准输出）。", "advanced", "bool", False),
    _item("ENABLE_CLUSTER", "启用集群", "启用多进程集群模式。", "advanced", "bool", False),
    _item("TITLE_LENGTH_LIMIT", "标题长度限制", "输出标题的最大长度（字符）。", "advanced", "int", 150, minimum=0, maximum=1000),
    # ---- Route Credentials (write-only secrets) ----
    _item("GITHUB_ACCESS_TOKEN", "GitHub Access Token", "GitHub 路由访问令牌。", "credentials", "secret", "", secret=True),
    _item("GITEE_ACCESS_TOKEN", "Gitee Access Token", "Gitee 路由访问令牌。", "credentials", "secret", "", secret=True),
    _item("ZHIHU_COOKIES", "知乎 Cookies", "知乎路由的 Cookie。", "credentials", "secret", "", secret=True),
    _item("DOUBAN_COOKIE", "豆瓣 Cookie", "豆瓣路由的 Cookie。", "credentials", "secret", "", secret=True),
    _item("WEIBO_COOKIES", "微博 Cookies", "微博路由的 Cookie。", "credentials", "secret", "", secret=True),
    _item("YOUTUBE_KEY", "YouTube Key", "YouTube 路由 API Key。", "credentials", "secret", "", secret=True),
    _item("XIAOHONGSHU_COOKIE", "小红书 Cookie", "小红书路由的 Cookie。", "credentials", "secret", "", secret=True),
    _item("SSPAI_BEARERTOKEN", "少数派 Bearer Token", "少数派路由的 Bearer Token。", "credentials", "secret", "", secret=True),
)

ITEMS_BY_KEY = {item.key: item for item in SCHEMA}
NON_SECRET_ITEMS = tuple(item for item in SCHEMA if not item.secret)
SECRET_ITEMS = tuple(item for item in SCHEMA if item.secret)

MAX_SECRET_LENGTH = 10000




def defaults() -> dict[str, Any]:
    """Merged defaults for every non-secret item."""
    return {item.key: item.default for item in NON_SECRET_ITEMS}


def _validate_value(item: ConfigItem, value: Any) -> Any:
    """Validate + normalize one non-secret value (raises RssHubInvalidValue)."""
    if item.type == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            raise RssHubInvalidValue(f"{item.key} must be an integer.")
        if item.minimum is not None and value < item.minimum:
            raise RssHubInvalidValue(f"{item.key} is below the allowed minimum.")
        if item.maximum is not None and value > item.maximum:
            raise RssHubInvalidValue(f"{item.key} is above the allowed maximum.")
        return value
    if item.type == "bool":
        if not isinstance(value, bool):
            raise RssHubInvalidValue(f"{item.key} must be a boolean.")
        return value
    if item.type == "enum":
        if not isinstance(value, str) or value not in (item.options or ()):
            raise RssHubInvalidValue(
                f"{item.key} must be one of {', '.join(item.options or ())}."
            )
        return value
    if not isinstance(value, str):
        raise RssHubInvalidValue(f"{item.key} must be a string.")
    if item.max_length is not None and len(value) > item.max_length:
        raise RssHubInvalidValue(f"{item.key} is too long.")
    if any(ord(char) < 32 for char in value):
        raise RssHubInvalidValue(f"{item.key} must not contain control characters.")
    return value


def _parse_document(raw: str | None) -> dict[str, Any]:
    """Parse a stored document; corrupt/future documents fall back to defaults."""
    document: dict[str, Any] = {
        "schemaVersion": RSSHUB_CONFIG_SCHEMA_VERSION,
        "values": {},
        "secretsVersion": 0,
    }
    if raw is None:
        return document
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return document
    if not isinstance(parsed, dict):
        return document
    values = parsed.get("values")
    if isinstance(values, dict):
        clean: dict[str, Any] = {}
        for key, value in values.items():
            item = ITEMS_BY_KEY.get(key)
            if item is None or item.secret:
                continue
            try:
                clean[key] = _validate_value(item, value)
            except RssHubControlError:
                continue
        document["values"] = clean
    version = parsed.get("secretsVersion")
    if isinstance(version, int) and version >= 0:
        document["secretsVersion"] = version
    return document


class RssHubControlStore:
    """Typed access to desired/applied RSSHub config + write-only secrets."""

    def __init__(self, db: Database, secrets: SecretsStore) -> None:
        self._db = db
        self._secrets = secrets

    async def _load_doc(self, key: str) -> dict[str, Any]:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT value FROM lumi_settings WHERE key = ?", (key,)
        )
        return _parse_document(row["value"] if row is not None else None)

    async def _save_doc(self, key: str, document: dict[str, Any]) -> None:
        await self._db.execute(
            "INSERT INTO lumi_settings (key, value, updated_at) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
            "updated_at = excluded.updated_at",
            (key, json.dumps(document, ensure_ascii=False, sort_keys=True), _utc_now()),
        )

    def effective(self, document: dict[str, Any]) -> dict[str, Any]:
        return {**defaults(), **document["values"]}

    async def desired(self) -> dict[str, Any]:
        return await self._load_doc(DESIRED_KEY)

    async def applied(self) -> dict[str, Any]:
        return await self._load_doc(APPLIED_KEY)

    async def patch_desired(self, values: dict[str, Any]) -> dict[str, Any]:
        """Validate + persist provided non-secret desired values."""
        document = await self.desired()
        updated: dict[str, Any] = {}
        for key, value in values.items():
            item = ITEMS_BY_KEY.get(key)
            if item is None:
                raise RssHubUnknownKey(f"unknown RSSHub config key '{key}'")
            if item.secret:
                raise RssHubInvalidValue(
                    f"'{key}' is a secret; use the secret endpoint."
                )
            if not item.editable:
                raise RssHubInvalidValue(f"'{key}' is not editable.")
            updated[key] = _validate_value(item, value)
        document["values"].update(updated)
        await self._save_doc(DESIRED_KEY, document)
        return self.effective(document)

    async def mark_applied(self) -> dict[str, Any]:
        """Operator confirms the desired config is now applied (snapshot)."""
        desired = await self.desired()
        applied = {
            "schemaVersion": RSSHUB_CONFIG_SCHEMA_VERSION,
            "values": dict(desired["values"]),
            "secretsVersion": desired["secretsVersion"],
        }
        await self._save_doc(APPLIED_KEY, applied)
        return self.effective(applied)

    async def restart_required_flags(self) -> dict[str, Any]:
        """Per-item restartRequired + pending secret flag + count."""
        desired = await self.desired()
        applied = await self.applied()
        eff_desired = self.effective(desired)
        eff_applied = self.effective(applied)
        flags = {
            item.key: eff_desired[item.key] != eff_applied[item.key]
            for item in NON_SECRET_ITEMS
        }
        pending_secrets = desired["secretsVersion"] != applied["secretsVersion"]
        count = sum(1 for flag in flags.values() if flag) + (1 if pending_secrets else 0)
        return {"flags": flags, "pendingSecrets": pending_secrets, "count": count}

    @staticmethod
    def _secret_store_key(env_key: str) -> str:
        return f"rsshub.{env_key}"

    def secret_configured_map(self) -> dict[str, bool]:
        keys = [item.key for item in SECRET_ITEMS]
        return {
            key: self._secrets.configured(self._secret_store_key(key)) for key in keys
        }

    async def set_secret(self, key: str, value: str) -> None:
        """Write one secret (write-only; bumps secretsVersion)."""
        item = ITEMS_BY_KEY.get(key)
        if item is None or not item.secret:
            raise RssHubUnknownKey(f"'{key}' is not a known secret key.")
        if not value.strip():
            raise RssHubInvalidValue("secret value must not be blank.")
        if len(value) > MAX_SECRET_LENGTH:
            raise RssHubInvalidValue("secret value is too long.")
        if any(ord(char) < 32 for char in value):
            raise RssHubInvalidValue(
                "secret value must not contain control characters."
            )
        self._secrets.set(self._secret_store_key(key), value)
        await self._bump_secrets_version()

    async def delete_secret(self, key: str) -> None:
        """Clear one secret (bumps secretsVersion)."""
        item = ITEMS_BY_KEY.get(key)
        if item is None or not item.secret:
            raise RssHubUnknownKey(f"'{key}' is not a known secret key.")
        self._secrets.delete(self._secret_store_key(key))
        await self._bump_secrets_version()

    async def _bump_secrets_version(self) -> None:
        document = await self.desired()
        document["secretsVersion"] = document["secretsVersion"] + 1
        await self._save_doc(DESIRED_KEY, document)


def config_view(
    store: RssHubControlStore,
    desired: dict[str, Any],
    flags: dict[str, Any],
) -> list[dict[str, Any]]:
    """Build the browser-safe group view (sync helper, secrets -> configured)."""
    eff_desired = store.effective(desired)
    secret_flags = store.secret_configured_map()
    groups: list[dict[str, Any]] = []
    for group_id, group_label in GROUP_LABELS.items():
        items: list[dict[str, Any]] = []
        for item in SCHEMA:
            if item.group != group_id:
                continue
            entry: dict[str, Any] = {
                "key": item.key,
                "label": item.label,
                "description": item.description,
                "group": item.group,
                "type": item.type,
                "default": item.default,
                "editable": item.editable,
                "secret": item.secret,
                "restartRequired": item.restart_required and flags["flags"].get(item.key, False),
                "options": list(item.options) if item.options else None,
            }
            if item.secret:
                entry["configured"] = secret_flags.get(item.key, False)
            else:
                entry["value"] = eff_desired[item.key]
            items.append(entry)
        groups.append({"id": group_id, "label": group_label, "items": items})
    return groups


def export_env(store: RssHubControlStore, desired: dict[str, Any]) -> str:
    """Render the desired config as an env fragment (secrets never echoed)."""
    effective = store.effective(desired)
    secret_flags = store.secret_configured_map()
    lines = [
        "# LumiRSS RSSHub config export (generated by the Control Center).",
        "# Apply these values to the RSSHub container environment, then restart",
        "# RSSHub and click \"mark as applied\" in the Control Center.",
        "",
    ]
    for item in NON_SECRET_ITEMS:
        value = effective[item.key]
        rendered = ("true" if value else "false") if item.type == "bool" else str(value)
        lines.append(f"{item.key}={rendered}")
    lines.append("")
    lines.append("# Secrets (configured in Lumi; set manually, never echoed):")
    for item in SECRET_ITEMS:
        if secret_flags.get(item.key):
            lines.append(f"# {item.key}=<configured>")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Custom site / route credentials (Gate) — metadata in lumi KV, values in
# the write-only SecretsStore. A custom credential maps ONE site to ONE
# RSSHub env key that its route actually reads; adding a site + a cookie
# can never conjure an RSSHub route that upstream does not have.
# ---------------------------------------------------------------------------

CUSTOM_CREDENTIALS_KEY = "rsshub.custom_credentials"
CUSTOM_SECRET_PREFIX = "rsshub.custom."

MAX_CUSTOM_CREDENTIALS = 32
CREDENTIAL_KINDS = ("cookie", "token", "api_key", "bearer", "other")

_CUSTOM_ENV_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_CUSTOM_DOMAIN_RE = re.compile(r"^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$")


class RssHubCustomCredentialError(RssHubControlError):
    """Browser-safe validation error for custom credential entries."""


def _validate_env_key(env_key: str) -> str:
    clean = env_key.strip()
    if not _CUSTOM_ENV_KEY_RE.match(clean):
        raise RssHubCustomCredentialError(
            "envKey must be UPPER_SNAKE_CASE (letters, digits, underscore, "
            "starting with a letter)."
        )
    return clean


def _validate_domain(domain: str) -> str:
    clean = domain.strip().lower().rstrip("/")
    if clean.startswith(("http://", "https://")) or "/" in clean or " " in clean:
        raise RssHubCustomCredentialError(
            "domain must be a bare hostname like example.com (no scheme/path)."
        )
    if len(clean) > 253 or not _CUSTOM_DOMAIN_RE.match(clean):
        raise RssHubCustomCredentialError("domain is not a valid hostname.")
    return clean


def _validate_credential_value(value: str) -> str:
    """Shared custom-credential value rules: non-blank, bounded, and free
    of control characters — rejected at INPUT time so env-file rendering
    can never fail on an already-stored value."""
    clean = value.strip()
    if not clean:
        raise RssHubCustomCredentialError("value must not be blank.")
    if len(clean) > MAX_SECRET_LENGTH:
        raise RssHubCustomCredentialError("value is too long.")
    if any(ord(ch) < 32 for ch in clean):
        raise RssHubCustomCredentialError(
            "value must not contain control characters."
        )
    return clean


def _validate_label_text(value: str, field: str, max_length: int) -> str:
    clean = value.strip()
    if not clean:
        raise RssHubCustomCredentialError(f"{field} must not be blank.")
    if len(clean) > max_length:
        raise RssHubCustomCredentialError(
            f"{field} must be at most {max_length} characters."
        )
    if any(ord(ch) < 32 for ch in clean):
        raise RssHubCustomCredentialError(
            f"{field} must not contain control characters."
        )
    return clean


class RssHubCustomCredentialStore:
    """CRUD for user-defined site-to-route-credential mappings."""

    def __init__(self, db: Database, secrets: SecretsStore) -> None:
        self._db = db
        self._secrets = secrets

    async def _load(self) -> list[dict[str, Any]]:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT value FROM lumi_settings WHERE key = ?",
            (CUSTOM_CREDENTIALS_KEY,),
        )
        if row is None or not row["value"]:
            return []
        try:
            parsed = json.loads(row["value"])
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []

    async def _save(self, entries: list[dict[str, Any]]) -> None:
        payload = json.dumps(entries, ensure_ascii=False, sort_keys=True)
        await self._db.execute(
            "INSERT INTO lumi_settings (key, value, updated_at) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
            "updated_at = excluded.updated_at",
            (CUSTOM_CREDENTIALS_KEY, payload, _utc_now()),
        )

    @staticmethod
    def _secret_key(entry_id: str) -> str:
        return CUSTOM_SECRET_PREFIX + entry_id

    async def list_entries(self) -> list[dict[str, Any]]:
        entries = await self._load()
        return [
            {
                "id": e["id"],
                "name": e["name"],
                "domain": e["domain"],
                "route": e["route"],
                "envKey": e["envKey"],
                "kind": e["kind"],
                "configured": self._secrets.configured(self._secret_key(e["id"])),
                "createdAt": e["createdAt"],
                "updatedAt": e["updatedAt"],
            }
            for e in entries
        ]

    async def create(
        self,
        *,
        name: str,
        domain: str,
        env_key: str,
        kind: str,
        value: str,
        route: str = "",
    ) -> dict[str, Any]:
        entries = await self._load()
        if len(entries) >= MAX_CUSTOM_CREDENTIALS:
            raise RssHubCustomCredentialError(
                f"Too many custom credentials (max {MAX_CUSTOM_CREDENTIALS})."
            )
        clean_name = _validate_label_text(name, "name", 80)
        clean_domain = _validate_domain(domain)
        clean_key = _validate_env_key(env_key)
        if clean_key in ITEMS_BY_KEY:
            # 固定 schema 键必须经 Control Center 管理：允许自定义凭据
            # 占用同名 envKey 会在 env 文件里 last-wins 静默遮蔽它。
            raise RssHubCustomCredentialError(
                f"envKey '{clean_key}' belongs to the fixed Control-Center "
                "schema; configure it there instead."
            )
        clean_route = route.strip()
        if len(clean_route) > 200:
            raise RssHubCustomCredentialError(
                "route must be at most 200 characters."
            )
        if kind not in CREDENTIAL_KINDS:
            raise RssHubCustomCredentialError(
                f"kind must be one of {', '.join(CREDENTIAL_KINDS)}."
            )
        for existing in entries:
            if existing["envKey"] == clean_key:
                raise RssHubCustomCredentialError(
                    f"envKey '{clean_key}' is already used."
                )
        clean_value = _validate_credential_value(value)
        entry_id = uuid.uuid4().hex[:16]
        now = _utc_now()
        entry = {
            "id": entry_id,
            "name": clean_name,
            "domain": clean_domain,
            "route": clean_route,
            "envKey": clean_key,
            "kind": kind,
            "createdAt": now,
            "updatedAt": now,
        }
        entries.append(entry)
        await self._save(entries)
        self._secrets.set(self._secret_key(entry_id), clean_value)
        view = await self.list_entries()
        return next(e for e in view if e["id"] == entry_id)

    async def update_metadata(
        self, entry_id: str, *, name: str | None = None, route: str | None = None
    ) -> dict[str, Any]:
        entries = await self._load()
        for entry in entries:
            if entry["id"] == entry_id:
                if name is not None:
                    entry["name"] = _validate_label_text(name, "name", 80)
                if route is not None:
                    if len(route.strip()) > 200:
                        raise RssHubCustomCredentialError(
                            "route must be at most 200 characters."
                        )
                    entry["route"] = route.strip()
                entry["updatedAt"] = _utc_now()
                await self._save(entries)
                view = await self.list_entries()
                return next(e for e in view if e["id"] == entry_id)
        raise RssHubCustomCredentialError("credential not found.")

    async def set_value(self, entry_id: str, value: str) -> None:
        entries = await self._load()
        if not any(e["id"] == entry_id for e in entries):
            raise RssHubCustomCredentialError("credential not found.")
        clean = _validate_credential_value(value)
        self._secrets.set(self._secret_key(entry_id), clean)

    async def delete(self, entry_id: str) -> None:
        entries = await self._load()
        remaining = [e for e in entries if e["id"] != entry_id]
        if len(remaining) == len(entries):
            raise RssHubCustomCredentialError("credential not found.")
        await self._save(remaining)
        self._secrets.delete(self._secret_key(entry_id))

    async def collect_values(self) -> dict[str, str]:
        """env key to value, for SERVER-SIDE env-file materialization only
        (values never reach the browser or the export endpoint)."""
        result: dict[str, str] = {}
        for entry in await self._load():
            value = self._secrets.get(self._secret_key(entry["id"]))
            if value:
                result[entry["envKey"]] = value
        return result


def _env_escape(key: str, value: str) -> str:
    """docker-compose env_file safe rendering: no control chars, no
    newlines, no shell eval anywhere in the pipeline."""
    if any(ord(ch) < 32 for ch in value):
        raise RssHubInvalidValue(
            f"'{key}' contains control characters and cannot be rendered."
        )
    return value


def render_env_file(
    store: RssHubControlStore,
    desired: dict[str, Any],
    custom_values: dict[str, str],
) -> str:
    """Materialize a complete RSSHub env file INCLUDING secret values.

    Server-side only: the caller writes this to a 0600 file under the BFF
    data dir and never returns it to the browser.
    """
    effective = store.effective(desired)
    secret_flags = store.secret_configured_map()
    lines = [
        "# LumiRSS RSSHub env file — GENERATED; apply via apply_rsshub_config.py",
        "# Contains secret values; keep on the BFF host, chmod 0600,",
        "# never commit and never serve to the browser.",
        "",
    ]
    for item in NON_SECRET_ITEMS:
        raw = effective[item.key]
        rendered = ("true" if raw else "false") if item.type == "bool" else str(raw)
        lines.append(f"{item.key}={_env_escape(item.key, rendered)}")
    for item in SECRET_ITEMS:
        if secret_flags.get(item.key):
            value = store._secrets.get(store._secret_store_key(item.key)) or ""
            lines.append(f"{item.key}={_env_escape(item.key, value)}")
    lines.append("")
    lines.append("# Custom site/route credentials (Control Center managed):")
    for env_key, value in custom_values.items():
        lines.append(f"{_env_escape(env_key, env_key)}={_env_escape(env_key, value)}")
    return "\n".join(lines) + "\n"
