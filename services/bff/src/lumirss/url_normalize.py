"""URL 规范化（F004 重复订阅检查器 / F018 相同链接聚合 共用子集）。

受控、保守的归一化规则（宁可漏合并，不可错合并）：

- 仅接受 http(s) 绝对 URL，其余原样返回 None（调用方按原 URL 处理）；
- host 小写；
- 去掉末尾斜杠（仅路径末尾的一个——不过度压缩多斜杠路径）；
- 丢弃已知追踪参数：utm_*（utm_source/utm_medium/…）、fbclid、
  gclid、gclid/msclkid/igshid/mc_cid/mc_eid（F004/F010 名单）；
- 签名类参数（*_signature、token、sig、key、access_token）绝不丢弃——
  带签名的 URL 视为不同资源（不过度归一化）；
- 路径不同 = 不同 URL（不同有效版本/文章不合并）；
- scheme（http/https）差异忽略；其余查询参数原样保留（保守）。

输出形态：``host/path?query``（无 scheme，供分组 key 使用）。

FIX-235：feed URL 身份用 :func:`normalize_feed_url`——查询参数对
feed 常是业务配置（如 RSSHub 路由的任意 query），一个都不丢；尾斜杠
同样只折一个。追踪参数丢弃只属于内容 URL 域。
"""

from urllib.parse import parse_qsl, urlencode, urlsplit

TRACKING_PARAM_PREFIXES = ("utm_",)
TRACKING_PARAM_EXACT = frozenset(
    {"fbclid", "gclid", "msclkid", "igshid", "mc_cid", "mc_eid"}
)
SIGNATURE_PARAM_EXACT = frozenset({"token", "sig", "key", "access_token"})


def _is_tracking_param(name: str) -> bool:
    lowered = name.lower()
    if any(lowered.startswith(prefix) for prefix in TRACKING_PARAM_PREFIXES):
        return True
    return lowered in TRACKING_PARAM_EXACT


def _is_signature_param(name: str) -> bool:
    lowered = name.lower()
    if lowered in SIGNATURE_PARAM_EXACT:
        return True
    return lowered.endswith("_signature")


def _split_http_url(url: str) -> tuple[str, str, str] | None:
    """(host, path, query) of an http(s) URL, or None when unusable."""
    if not isinstance(url, str) or not url.strip():
        return None
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    path = parts.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]  # 只去一个尾斜杠（FIX-235：不过度压缩）
    return parts.hostname.lower(), path, parts.query


def normalize_feed_url(url: str) -> str | None:
    """Feed URL 的保守归一化（FIX-235，重复订阅候选分组键）。

    host 小写、scheme 忽略、路径只折一个尾斜杠；**查询参数逐字符
    原样保留**——对 feed 而言任意 query 都可能有业务意义（RSSHub
    路由配置等），丢参数会把两个不同订阅错并成一个。解析失败 /
    非 http(s) → None。
    """
    split = _split_http_url(url)
    if split is None:
        return None
    host, path, query = split
    return f"{host}{path}{'?' + query if query else ''}"


def normalize_content_url(url: str) -> str | None:
    """规范化 URL；非 http(s) 或解析失败 → None。"""
    split = _split_http_url(url)
    if split is None:
        return None
    host, path, query = split
    if query:
        try:
            pairs = parse_qsl(query, keep_blank_values=True)
        except ValueError:
            pairs = []
        kept = [
            (name, value)
            for name, value in pairs
            if not _is_tracking_param(name)
        ]
        query = urlencode(kept)
    return f"{host}{path}{'?' + query if query else ''}"
