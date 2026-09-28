"""R2 BFF14 — vault/markdown 域 FIX 项的行为证据。

每个测试编码对应 FIX 项的验收规则；实现已满足规则的，通过的测试即
BASELINE_OK 核验证据（BASELINE 标注）；实现不满足的先以失败复现再修
（FIXED 标注）。凭据/内容均为运行时生成的假数据；vault 全部用隔离的
tmp_path，绝不触碰开发者真实目录。

覆盖：FIX-331（扫描不跟随越界符号链接）、FIX-335（附件绝对路径不落
到宿主机解析）、FIX-334（同名 wikilink 确定性解析）、FIX-337（vault
只读边界 + 本地修正只在 Lumi 层）、FIX-333（frontmatter 类型异常单文
件降级）、FIX-338（BOM/CRLF/代码块保真）、FIX-349（附件 Range 请求）、
FIX-328（快照存储/读出双边界禁活动内容 + 原始 URL 保留）。
"""

import ast
import asyncio
import hashlib
from pathlib import Path

import pytest

from lumirss.obsidian import ObsidianService, check_vault_path
from lumirss.obsidian_backlinks import rebuild_backlinks
from lumirss.obsidian_handoff import validate_export_markdown
from lumirss.storage import Database


def run(coroutine):
    return asyncio.run(coroutine)


@pytest.fixture()
def obsidian(tmp_path):
    db = Database(tmp_path / "lumi.sqlite")
    run(db.migrate())
    return ObsidianService(db), tmp_path


def _write_vault(tmp_path: Path, files: dict[str, str]) -> Path:
    vault = tmp_path / "vault"
    for rel, content in files.items():
        target = vault / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return vault


def _hash_vault(vault: Path) -> dict[str, str]:
    return {
        path.relative_to(vault).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(vault.rglob("*"))
        if path.is_file() and not path.is_symlink()
    }


# ---------------------------------------------------------------------------
# FIX-331 — 扫描笔记库跟随符号链接越过用户选定根目录：默认不跟随外链。
#
# BASELINE 核验：vault 内的符号链接（文件或目录）指向根外时，逐项
# resolve + containment 拒绝（obsidian._contained），既不入投影也不读
# 内容；根内的普通文件照常索引。
# ---------------------------------------------------------------------------


def test_fix331_scan_does_not_follow_escaping_symlinks(obsidian, tmp_path):
    service, tmp = obsidian
    outside = tmp / "outside"
    outside.mkdir()
    (outside / "topsecret.md").write_text(
        "---\ntitle: TOPSECRET\n---\nhost-secret-body\n", encoding="utf-8"
    )
    (tmp / "host-file.md").write_text(
        "---\ntitle: HOSTFILE\n---\nhost-file-body\n", encoding="utf-8"
    )
    vault = _write_vault(
        tmp, {"notes/regular.md": "---\ntitle: 常规笔记\n---\n普通内容\n"}
    )
    # 文件级逃逸 + 目录级逃逸（目录符号链接内还有 .md）。
    (vault / "escape-file.md").symlink_to(tmp / "host-file.md")
    (vault / "linked-dir").symlink_to(outside)

    run(service.set_vault_path(str(vault)))
    report = run(service.rescan())

    assert report["added"] == 1  # 只有根内普通文件被索引
    assert report["skipped"] >= 2  # 两个逃逸链接被拒
    notes = run(service.list_notes())
    rels = {n["relPath"] for n in notes}
    assert rels == {"notes/regular.md"}
    # 越界内容零泄漏：标题与正文都不出现在投影里。
    for note in notes:
        assert "TOPSECRET" not in note["title"]
        assert "HOSTFILE" not in note["title"]
    rows = run(service._db.fetch_all("SELECT body_text FROM obsidian_notes"))
    joined = " ".join(str(row["body_text"]) for row in rows)
    assert "host-secret-body" not in joined
    assert "host-file-body" not in joined
    # 根内普通文件确实被读到了（不是「全部拒读」的假阳性通过）。
    assert any("普通内容" in str(row["body_text"]) for row in rows)


# ---------------------------------------------------------------------------
# FIX-335 — Markdown 内部附件路径被当成服务器绝对路径：以授权资料根
# 解析，不能读取宿主机文件。
#
# BASELINE 核验：check_vault_path 对绝对路径/穿越路径一律 containment
# 拒绝（返回 None「无法核对」），绝不把宿主机绝对路径解析成「存在」，
# 也绝不读宿主机文件内容；vault 内相对路径附件照常核对。
# ---------------------------------------------------------------------------


def test_fix335_absolute_attachment_paths_never_resolve_outside_vault(
    obsidian, tmp_path
):
    service, tmp = obsidian
    vault = _write_vault(tmp, {"notes/regular.md": "正文\n"})
    (vault / "assets").mkdir()
    (vault / "assets" / "pic.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
    # 宿主机上的真实文件（若实现误用绝对路径解析，它「存在」且可读）。
    host_secret = tmp / "host-secret.png"
    host_secret.write_bytes(b"\x89PNG\r\n\x1a\nhost-secret")

    run(service.set_vault_path(str(vault)))

    assert check_vault_path(str(vault), "assets/pic.png") is True
    assert check_vault_path(str(vault), "assets/missing.png") is False
    # 绝对路径（/etc/passwd 风格 / 宿主机临时路径）与穿越：一律 None，
    # 绝不返回 True（宿主机文件存在性绝不经由附件路径泄露）。
    assert check_vault_path(str(vault), "/etc/passwd") is None
    assert check_vault_path(str(vault), str(host_secret)) is None
    assert check_vault_path(str(vault), "assets/../../host-secret.png") is None
    # `~` 不做 expanduser：按 vault 内字面量相对路径核对（missing），
    # 绝不落到宿主机 $HOME。
    assert check_vault_path(str(vault), "~/.ssh/id_rsa") is False


def test_fix335_export_validation_never_blesses_host_absolute_attachments(
    obsidian, tmp_path
):
    """导出校验只按投影/vault 相对路径核对；绝对路径附件不会被当成
    「vault 内存在」而放行进报告（诚实：核对不了就不核对）。"""
    service, tmp = obsidian
    vault = _write_vault(tmp, {"notes/n.md": "正文\n"})
    run(service.set_vault_path(str(vault)))
    host_secret = tmp / "host-secret.png"
    host_secret.write_bytes(b"host")

    markdown = (
        "![真实缺失](assets/really-missing.png)\n"
        "![宿主机绝对路径](/etc/passwd)\n"
        f"![宿主机文件]({host_secret})\n"
    )
    issues = validate_export_markdown(
        markdown,
        projection_index={},
        vault_exists=lambda rel: check_vault_path(str(vault), rel),
    )
    kinds = [issue["kind"] for issue in issues]
    assert "missing_attachment" in kinds  # 真实相对缺失照报
    missing_details = " ".join(
        issue["detail"] for issue in issues if issue["kind"] == "missing_attachment"
    )
    assert "/etc/passwd" not in missing_details
    assert str(host_secret) not in missing_details
    assert "host-secret" not in missing_details


# ---------------------------------------------------------------------------
# FIX-337 — 只读连接中的本地修正反写源笔记：个人修正保存于 LumiRSS
# 独立层，原库文件哈希不变。
#
# BASELINE 核验（两层证据）：
# 1) 运行时：整轮 vault 交互（扫描/查看/反链/附件核对/导出校验）前后
#    vault 每个文件 sha256 逐字节一致；派生态只写进 Lumi 自己的 sqlite。
# 2) 静态：vault 触达模块源码中不存在任何写能力调用（write_text/
#    write_bytes/unlink/rename/mkdir/open-w…）。
# ---------------------------------------------------------------------------


_VAULT_TOUCHING_MODULES = (
    "obsidian",
    "obsidian_backlinks",
    "obsidian_handoff",
)

_FORBIDDEN_WRITE_CALLS = frozenset(
    {
        "write_text",
        "write_bytes",
        "unlink",
        "mkdir",
        "rename",
        "rmdir",
        "touch",
        "rmtree",
        "open",
    }
)
# 注：Path.replace（≡ rename）无法与无处不在的 str.replace 在无类型
# AST 里区分，不进静态黑名单；改名防线由 rename + 运行时字节哈希测试
# （test_fix337_full_note_lifecycle_leaves_vault_bytes_unchanged）承担。


def test_fix337_vault_modules_contain_no_write_capability():
    """静态守卫：vault 触达模块没有任何写文件调用（架构不变量的可执行
    形式：写路径在 AST 层就不存在，而不是「恰好没被调用」）。"""
    import lumirss

    package_dir = Path(lumirss.__file__).parent
    for module_name in _VAULT_TOUCHING_MODULES:
        source = (package_dir / f"{module_name}.py").read_text(encoding="utf-8")
        tree = ast.parse(source, filename=f"{module_name}.py")
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = (
                    func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
                )
                if name not in _FORBIDDEN_WRITE_CALLS:
                    continue
                raise AssertionError(
                    f"{module_name}.py 含写能力调用 {name!r}（line {node.lineno}）"
                )


def test_fix337_full_note_lifecycle_leaves_vault_bytes_unchanged(obsidian, tmp_path):
    service, tmp = obsidian
    vault = _write_vault(
        tmp,
        {
            "a/note.md": "---\ntitle: 目标笔记\n---\n正文 [[其他]]\n",
            "b/other.md": "---\ntitle: 其他\n---\n其他正文\n",
            "assets/pic.png": "",
        },
    )
    run(service.set_vault_path(str(vault)))
    before = _hash_vault(vault)

    first = run(service.rescan())
    second = run(service.rescan())  # 幂等重扫
    note = run(service.list_notes())[0]
    detail = run(service.get_note(note["ref"].split(":", 1)[1]))
    assert detail is not None
    backlinks = run(rebuild_backlinks(service._db))
    assert backlinks >= 0
    assert (
        check_vault_path(str(vault), "assets/pic.png") is True
    )  # 附件核对（只读）
    validate_export_markdown(
        "[[目标笔记]]", projection_index={"目标笔记": "a/note.md"}
    )

    assert first["added"] == 2  # 只索引 .md（附件文件不入投影）
    assert second["added"] == 0
    assert _hash_vault(vault) == before  # 原库逐字节不变
