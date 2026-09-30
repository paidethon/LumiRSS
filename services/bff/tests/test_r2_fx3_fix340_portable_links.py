"""FIX-340 — 导出回链误含本机绝对路径和用户名（真修）。

裁决：真修。可移植打包此前只重写图片/嵌入引用；普通 Markdown 链接
``[text](target)`` 原样进包——``/home/<user>/…``、``file:///C:/Users/
<user>/…``、``..`` 越界引用全部残留，公共包暴露主机目录与用户名。
修复：普通链接在图片腿之后同口径裁决（本机路径 → 移除 + 如实记
local_path_link violation），终检（双保险）扩展到普通链接；远程与包内
相对链接（``../attachments/``、http(s)、obsidian:）不受影响。
"""

import asyncio

from lumirss.new326_portable_bundle import (
    PortableBundleBuilder,
    _is_host_local_target,
)
from lumirss.obsidian import ObsidianService
from lumirss.storage import Database

HOST_NOTE = """# 导出笔记

[秘密](/home/alice/secret/notes.md)

[文档](file:///C:/Users/bob/doc.pdf)

[盘符](C:\\Users\\carol\\report.md)

[上跳](../outside.md)

[网页](https://example.com/article)

[应用](obsidian://open?vault=v&file=n)

![图](pic.png)
"""


def _seed(tmp_path, text: str):
    async def scenario():
        vault = tmp_path / "vault"
        vault.mkdir()
        (vault / "a.md").write_text(text, encoding="utf-8")
        (vault / "pic.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
        db = Database(tmp_path / "lumi.sqlite")
        await db.migrate()
        service = ObsidianService(db)
        await service.set_vault_path(str(vault))
        await service.rescan()
        rows = await db.fetch_all("SELECT item_uuid FROM obsidian_notes")
        builder = PortableBundleBuilder(db, str(vault))
        return builder, await builder.build([str(r["item_uuid"]) for r in rows])

    return asyncio.run(scenario())


def test_host_local_links_removed_from_public_bundle(tmp_path):
    builder, result = _seed(tmp_path, HOST_NOTE)
    text = result["files"]["notes/a.md"].decode()
    # 本机路径与用户名不再出现在公共包内容里。
    assert "/home/alice" not in text
    assert "file:///C:/Users/bob" not in text
    assert "C:\\Users\\carol" not in text
    assert "../outside.md" not in text
    # 诚实台账：每个被移除的链接都有 local_path_link violation。
    kinds = [v["kind"] for v in result["manifest"]["violations"]]
    assert kinds.count("local_path_link") == 4
    # 远程/逻辑链接与已收录附件不受影响。
    assert "[网页](https://example.com/article)" in text
    assert "[应用](obsidian://open?vault=v&file=n)" in text
    assert "![图](../attachments/pic.png)" in text
    # 终检（双保险）对该包零残留违规。
    leftover = builder._final_boundary_check(result["files"])
    assert leftover == []


def test_marker_comment_explains_removal(tmp_path):
    """被移除链接处留下诚实注释，读者知道内容被剥离及去向。"""
    _builder, result = _seed(tmp_path, HOST_NOTE)
    text = result["files"]["notes/a.md"].decode()
    assert "此处链接指向本机路径" in text
    assert "详见 manifest violations" in text


def test_final_boundary_check_flags_residual_plain_links(tmp_path):
    """终检独立兜底：手工构造的残留本机链接（绕过重写腿）也被判违规。"""
    builder = PortableBundleBuilder(Database(":memory:"), "")
    files = {
        "notes/x.md": (
            "[残留](/etc/passwd)\n\n[越界](../../evil.md)\n\n[合规](../attachments/a.png)\n"
        ).encode()
    }
    violations = builder._final_boundary_check(files)
    details = " ".join(v["detail"] for v in violations)
    assert "残留](/etc/passwd" in details or "/etc/passwd" in details
    assert "../../evil.md" in details
    assert "a.png" not in details  # 正确的包内相对链接不违规


def test_host_local_predicate_matrix():
    """谓词矩阵：本机路径形态命中；远程/包内相对形态放行。"""
    assert _is_host_local_target("/home/alice/x.md")
    assert _is_host_local_target("file:///C:/Users/bob/x.pdf")
    assert _is_host_local_target("C:\\Users\\carol\\x.md")
    assert _is_host_local_target("C:/Users/carol/x.md")
    assert _is_host_local_target("\\\\server\\share\\x.md")
    assert _is_host_local_target("../outside.md")
    assert _is_host_local_target("..\\outside.md")
    assert not _is_host_local_target("https://example.com/x")
    assert not _is_host_local_target("//example.com/x")  # 协议相对远程 URL
    assert not _is_host_local_target("obsidian://open?vault=v")
    assert not _is_host_local_target("data:text/plain;base64,AAAA")
    assert not _is_host_local_target("sub/dir/note.md")
    # 注：``../attachments/…`` 只存在于改写后的包内文本；谓词仅作用于
    # 原始笔记（lookbehind 保证改写产物不二次进入本裁决），包内相对
    # 链接的存活由 test_host_local_links_removed_from_public_bundle 的
    # ``![图](../attachments/pic.png)`` 端到端断言与终检 normpath 覆盖。
    assert not _is_host_local_target("")
