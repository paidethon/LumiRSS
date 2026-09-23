"""Obsidian URI builder (P16 多设备交接) — official schemes only.

Only the two OFFICIAL Obsidian URL schemes are ever generated here:

- ``obsidian://open?vault=<name>&file=<path>``  — open an existing note;
- ``obsidian://new?vault=<name>&file=<name>&content=<markdown>`` — hand
  content to the user's Obsidian, which creates the note AFTER the user
  confirms saving inside the app.

``obsidian://advanced-uri`` is a COMMUNITY plugin — it is never generated.
The vault stays read-only server-side (ADR 0004): a URI does not write
anything; it opens the user's own Obsidian app on their own device, and
the user confirms any save there.

Hard rules:

- vault name must be non-empty (a URI without a vault silently opens the
  wrong vault in Obsidian — refuse instead);
- note paths are vault-RELATIVE, forward slashes, no ``..`` traversal,
  no absolute local paths (host/container paths are meaningless on the
  user's device and never leave the server anyway);
- length guard: percent-encoded URIs longer than :data:`MAX_URI_LENGTH`
  (8000 — conservative across browsers/OS handlers) are rejected with
  ``{'tooLong': True, 'suggested': 'file'}`` so the caller falls back to
  a file download + clipboard, never a truncated silent handoff.
"""

import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import quote

MAX_URI_LENGTH = 8000

SUGGESTED_FALLBACK = "file"

_TOO_LONG: dict[str, Any] = {"tooLong": True, "suggested": SUGGESTED_FALLBACK}

_PLATFORMS = ("windows", "ios", "ipados", "other")

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


class ObsidianUriInvalid(ValueError):
    """Device profile / note path cannot produce a safe URI."""


def validate_platform(platform: str) -> str:
    if platform not in _PLATFORMS:
        raise ObsidianUriInvalid(
            f"platform 必须是 {'/'.join(_PLATFORMS)} 之一。"
        )
    return platform


def validate_vault_name(vault_name: str) -> str:
    vault = str(vault_name or "").strip()
    if not vault:
        raise ObsidianUriInvalid("Vault 名称不能为空。")
    return vault


def sanitize_note_path(path: str) -> str:
    """Vault-relative note path with forward slashes; traversal-proof.

    Backslashes become slashes (Windows habits), leading/trailing and
    duplicated slashes collapse, ``.``/``..`` segments are dropped (they
    can never escape the vault), control characters are removed. An
    absolute local path is reduced to its vault-relative tail — it can
    never survive as an absolute reference.
    """
    cleaned = _CONTROL_CHARS.sub("", str(path or "")).replace("\\", "/")
    segments = [
        segment.strip()
        for segment in cleaned.split("/")
        if segment.strip() not in ("", ".", "..")
    ]
    return "/".join(segments)


def _obsidian_uri(base: str, params: list[tuple[str, str]]) -> str:
    query = "&".join(
        f"{key}={quote(value, safe='')}" for key, value in params if value != ""
    )
    return f"obsidian://{base}?{query}"


def _guarded(uri: str) -> dict[str, Any]:
    if len(uri) > MAX_URI_LENGTH:
        return dict(_TOO_LONG)
    return {"uri": uri}


def build_obsidian_uri(profile: Mapping[str, Any], *, note_path: str) -> dict[str, Any]:
    """``obsidian://open`` deep link for one device profile.

    ``profile`` is a device-profile row/dict (``vault_name`` required;
    ``platform`` validated — windows/ios/ipados/other all emit the same
    official ``vault``+``file`` shape, and a local absolute path can
    never leak because :func:`sanitize_note_path` strips it for every
    platform). Returns ``{'uri': str}`` or the tooLong fallback dict.
    """
    vault = validate_vault_name(str(profile.get("vault_name") or ""))
    validate_platform(str(profile.get("platform") or "other"))
    path = sanitize_note_path(note_path)
    if not path:
        raise ObsidianUriInvalid("笔记路径不能为空。")
    return _guarded(_obsidian_uri("open", [("vault", vault), ("file", path)]))


def build_obsidian_new_uri(
    profile: Mapping[str, Any], *, file_name: str, content: str
) -> dict[str, Any]:
    """``obsidian://new`` handoff URI (official "create note" scheme).

    ``file_name`` is the new note's name (vault-relative; folders allowed
    via forward slashes), ``content`` the rendered Markdown. The guard
    measures the FULL encoded URI — content is percent-encoded first, so
    CJK-heavy articles hit the budget much sooner than their raw length
    suggests. Returns ``{'uri': str}`` or the tooLong fallback dict.
    """
    vault = validate_vault_name(str(profile.get("vault_name") or ""))
    validate_platform(str(profile.get("platform") or "other"))
    name = sanitize_note_path(file_name)
    if not name:
        raise ObsidianUriInvalid("笔记名称不能为空。")
    return _guarded(
        _obsidian_uri(
            "new", [("vault", vault), ("file", name), ("content", str(content or ""))]
        )
    )
