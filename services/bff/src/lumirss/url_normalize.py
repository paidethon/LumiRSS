"""URL 规范化（F004 重复订阅检查器 / F018 相同链接聚合 共用子集）。

受控、保守的归一化规则（宁可漏合并，不可错合并）：

- 仅接受 http(s) 绝对 URL，其余原样返回 None（调用方按原 URL 处理）；
- host 小写；
- 去掉末尾斜杠（仅路径末尾的一个）；
- 丢弃已知追踪参数：utm_*（utm_source/utm_medium/…）、fbclid、gclid、
  gclid/msclkid/igshid/mc_cid/mc_eid（F004/F010 名单）；
- 签名类参数（*_signature、token、sig、key、access_token）绝不丢弃——
  带签名的 URL 视为不同资源（不过度归一化）；
- 路径不同 = 不同 URL（不同有效版本/文章不合并）；
- scheme（http/https）差异忽略；其余查询参数原样保留（保守）。

输出形态：``host/path?query``（无 scheme，供分组 key 使用）。
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


def normalize_content_url(url: str) -> str | None:
    """规范化 URL；非 http(s) 或解析失败 → None。"""
    if not isinstance(url, str) or not url.strip():
        return None
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    host = parts.hostname.lower()
    path = parts.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    query = parts.query
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
