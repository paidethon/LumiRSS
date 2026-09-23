"""P16 obsidian_uri — 官方 scheme 专用（open/new），平台变体、CJK、
斜杠归一、路径穿越消毒、8000 字符 tooLong 守卫。"""

import pytest

from lumirss.obsidian_uri import (
    MAX_URI_LENGTH,
    ObsidianUriInvalid,
    build_obsidian_new_uri,
    build_obsidian_uri,
    sanitize_note_path,
)

WINDOWS = {"label": "台式机", "vault_name": "我的笔记库", "platform": "windows"}
IPHONE = {"label": "iPhone", "vault_name": "我的笔记库", "platform": "ios"}
IPAD = {"label": "iPad", "vault_name": "我的笔记库", "platform": "ipados"}
OTHER = {"label": "Linux 盒子", "vault_name": "我的笔记库", "platform": "other"}


class TestBuildOpenUri:
    def test_windows_vault_and_file_encoded(self):
        result = build_obsidian_uri(WINDOWS, note_path="日记/2026/随笔.md")
        uri = result["uri"]
        assert uri.startswith("obsidian://open?")
        assert "vault=%E6%88%91%E7%9A%84%E7%AC%94%E8%AE%B0%E5%BA%93" in uri
        assert "file=" in uri
        # path uses forward slashes, percent-encoded (raw '/' must not survive)
        assert "file=%E6%97%A5%E8%AE%B0%2F2026%2F%E9%9A%8F%E7%AC%94.md" in uri
        assert result.get("tooLong") is None

    def test_platform_variants_share_official_shape(self):
        # windows / ios / ipados / other 全部是官方 vault+file 形状；
        # 绝不出现本地绝对路径（file:// 或盘符）。
        for profile in (WINDOWS, IPHONE, IPAD, OTHER):
            result = build_obsidian_uri(profile, note_path="a/b.md")
            assert result["uri"].startswith("obsidian://open?vault=")
            assert "file=a%2Fb.md" in result["uri"]
            assert "file://" not in result["uri"]
            assert result["uri"].count("vault=") == 1

    def test_cjk_vault_and_path(self):
        result = build_obsidian_uri(IPHONE, note_path="中文 目录/笔记 名.md")
        assert "%E4%B8%AD%E6%96%87" in result["uri"]
        assert " " not in result["uri"].split("?")[1].split("&")[0]

    def test_invalid_platform_rejected(self):
        with pytest.raises(ObsidianUriInvalid):
            build_obsidian_uri(
                {"label": "x", "vault_name": "v", "platform": "android"},
                note_path="a.md",
            )

    def test_empty_vault_rejected(self):
        with pytest.raises(ObsidianUriInvalid):
            build_obsidian_uri({"label": "x", "vault_name": "  "}, note_path="a.md")

    def test_empty_path_rejected(self):
        with pytest.raises(ObsidianUriInvalid):
            build_obsidian_uri(WINDOWS, note_path=" .. ")


class TestSanitizeNotePath:
    def test_traversal_segments_dropped(self):
        # 逐段丢弃「..」（不做事词典解）：保证结果里永远不残留任何
        # 上跳段 —— 产物只能落在 vault 内部相对路径上。
        assert sanitize_note_path("../../etc/passwd") == "etc/passwd"
        assert ".." not in sanitize_note_path("a/../../b.md").split("/")
        assert sanitize_note_path("a/../../b.md") == "a/b.md"

    def test_backslashes_become_slashes(self):
        assert sanitize_note_path("日记\\2026\\笔记.md") == "日记/2026/笔记.md"

    def test_absolute_local_path_reduced(self):
        # 绝对路径永不原样透传（容器/宿主路径对用户设备无意义）；
        # 反斜杠归一后盘符也只是普通段 —— 结果不含上跳、不以 / 开头。
        assert sanitize_note_path("/srv/vault/notes/a.md") == "srv/vault/notes/a.md"
        assert sanitize_note_path("C:\\vault\\a.md") == "C:/vault/a.md"

    def test_control_chars_removed(self):
        assert sanitize_note_path("a\x00b.md") == "ab.md"

    def test_dots_and_empty(self):
        assert sanitize_note_path("./a/./b.md") == "a/b.md"
        assert sanitize_note_path("  ") == ""


class TestBuildNewUri:
    def test_new_uri_shape(self):
        result = build_obsidian_new_uri(
            WINDOWS, file_name="文章标题.md", content="# 标题\n\n正文"
        )
        uri = result["uri"]
        assert uri.startswith("obsidian://new?")
        assert "file=%E6%96%87%E7%AB%A0%E6%A0%87%E9%A2%98.md" in uri
        assert "content=%23%20%E6%A0%87%E9%A2%98" in uri

    def test_advanced_uri_never_generated(self):
        # advanced-uri 是社区插件 —— 任何输入都不得出现该 scheme。
        for uri in (
            build_obsidian_uri(WINDOWS, note_path="a.md").get("uri", ""),
            build_obsidian_new_uri(WINDOWS, file_name="a.md", content="x").get("uri", ""),
        ):
            assert "advanced-uri" not in uri

    def test_too_long_guard_returns_file_suggestion(self):
        # 8000 字符预算按【编码后】URI 计量 —— 大段中文正文会远超。
        huge = "汉" * 6000  # 每字编码 9 字符
        result = build_obsidian_new_uri(
            WINDOWS, file_name="长文.md", content=huge
        )
        assert result == {"tooLong": True, "suggested": "file"}
        assert "uri" not in result

    def test_oversized_open_uri_also_guarded(self):
        result = build_obsidian_uri(WINDOWS, note_path=("长" * 5000) + ".md")
        assert result == {"tooLong": True, "suggested": "file"}

    def test_at_budget_boundary_passes(self):
        # 编码后恰好 ≤ MAX_URI_LENGTH 的 URI 原样返回。
        content = "a" * (MAX_URI_LENGTH - len("obsidian://new?vault=&file=x.md&content=") - 50)
        result = build_obsidian_new_uri(WINDOWS, file_name="x.md", content=content)
        assert "uri" in result
        assert len(result["uri"]) <= MAX_URI_LENGTH
