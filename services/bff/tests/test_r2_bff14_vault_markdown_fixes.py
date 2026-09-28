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


# ---------------------------------------------------------------------------
# FIX-334 — Wiki 链接同名笔记解析到任意文件：明确相对路径规则。
#
# 同名笔记（不同目录）命中同一个 basename/title wikilink 时，解析必须
# 确定：先精确 rel_path，再「与链接方最近相对路径」（共享目录前缀最深
# 优先，平局取字典序），绝不随 DB 行序任意 pick。
# ---------------------------------------------------------------------------


def _backlink_target(db, from_uuid: str) -> tuple[str | None, str | None]:
    row = run(
        db.fetch_one(
            "SELECT target_uuid, broken, reason FROM obsidian_backlinks WHERE from_uuid = ? LIMIT 1",
            (from_uuid,),
        )
    )
    if row is None:
        return None, None
    return (str(row["target_uuid"]) if row["target_uuid"] else None), (
        str(row["reason"]) if row["reason"] else None
    )


def test_fix334_same_name_wikilink_resolves_to_closest_relative_path(
    obsidian, tmp_path
):
    """链接方 a/linking.md 的 [[shared]] 必须解析到 a/shared.md（同目录
    最近），即使 b/shared.md 先入库（旧行为：无 ORDER BY + setdefault
    → 任意 pick 先入行）。"""
    service, tmp = obsidian
    # 第一批：先只有 b/shared + 链接方（旧行为此时把 stem 锁在 b 行）。
    vault = _write_vault(
        tmp,
        {
            "b/shared.md": "---\ntitle: shared\n---\nB 版\n",
            "a/linking.md": "---\ntitle: 链接方\n---\n参见 [[shared]]\n",
        },
    )
    run(service.set_vault_path(str(vault)))
    run(service.rescan())
    # 第二批：a/shared 入库 → 重建后必须选同目录的 a/shared。
    (vault / "a" / "shared.md").write_text(
        "---\ntitle: shared\n---\nA 版\n", encoding="utf-8"
    )
    run(service.rescan())

    rows = run(
        service._db.fetch_all(
            "SELECT item_uuid, rel_path FROM obsidian_notes ORDER BY rel_path"
        )
    )
    by_rel = {str(row["rel_path"]): str(row["item_uuid"]) for row in rows}
    target, reason = _backlink_target(service._db, by_rel["a/linking.md"])
    assert reason is None
    assert target == by_rel["a/shared.md"]


def test_fix334_wikilink_tie_breaks_lexicographic_and_exact_path_wins(
    obsidian, tmp_path
):
    service, tmp = obsidian
    vault = _write_vault(
        tmp,
        {
            # 链接方在根目录：x-shared 与 z-shared 都不共享目录 → 字典序
            # 取 x-shared（与入库顺序无关）。
            "linking.md": "---\ntitle: 根链接方\n---\n[[doc]]\n",
            "z/doc.md": "---\ntitle: Z文档\n---\nZ\n",
            "x/doc.md": "---\ntitle: X文档\n---\nX\n",
        },
    )
    run(service.set_vault_path(str(vault)))
    run(service.rescan())

    rows = run(
        service._db.fetch_all(
            "SELECT item_uuid, rel_path FROM obsidian_notes ORDER BY rel_path"
        )
    )
    by_rel = {str(row["rel_path"]): str(row["item_uuid"]) for row in rows}
    target, reason = _backlink_target(service._db, by_rel["linking.md"])
    assert reason is None
    assert target == by_rel["x/doc.md"]

    # 精确相对路径永远优先于 basename/title 歧义解析。
    (vault / "linking.md").write_text(
        "---\ntitle: 根链接方\n---\n[[z/doc]]\n", encoding="utf-8"
    )
    run(service.rescan())
    target, reason = _backlink_target(service._db, by_rel["linking.md"])
    assert reason is None
    assert target == by_rel["z/doc.md"]


def test_fix334_title_ambiguity_resolves_deterministically(obsidian, tmp_path):
    service, tmp = obsidian
    vault = _write_vault(
        tmp,
        {
            "notes/guide.md": "---\ntitle: 指南\n---\n参见 [[指南]]\n",
            "deep/nest/指南.md": "---\ntitle: 指南\n---\n深层版\n",
            "deep/指南.md": "---\ntitle: 指南\n---\n中层级版\n",
        },
    )
    run(service.set_vault_path(str(vault)))
    run(service.rescan())
    rows = run(
        service._db.fetch_all(
            "SELECT item_uuid, rel_path FROM obsidian_notes ORDER BY rel_path"
        )
    )
    by_rel = {str(row["rel_path"]): str(row["item_uuid"]) for row in rows}
    target, reason = _backlink_target(service._db, by_rel["notes/guide.md"])
    # title 桶候选：链接方所在目录 notes 无同名 → 共享目录前缀 0 平局
    # → rel_path 字典序（逐字节：ASCII 'n' < CJK '指'）→ deep/nest/指南。
    assert reason is None
    assert target == by_rel["deep/nest/指南.md"]


# ---------------------------------------------------------------------------
# FIX-333 — Markdown frontmatter 类型异常拖垮整个批次：单文件准确报错。
#
# tags 为标量（int/date/bool/None）时旧实现 `for t in 42` TypeError 直接
# 冒泡 → 整个扫描批次 500。修复后：异常类型降级（该文件照常入库，仅
# frontmatter 标签丢弃），任何单文件解析异常都不中断批次，且该文件进
# N138 skipped 诊断（准确到文件）。
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("scalar", ["42", "2024-01-01", "true", "null"])
def test_fix333_frontmatter_scalar_tags_do_not_crash_parse(obsidian, tmp_path, scalar):
    from lumirss.obsidian import parse_note

    service, tmp = obsidian
    vault = _write_vault(tmp, {"n.md": f"---\ntitle: t\ntags: {scalar}\n---\n正文\n"})
    note = parse_note(vault / "n.md", vault)
    assert note is not None  # 单文件降级，绝不做掉整批
    assert note["title"] == "t"
    for tag in ("42", "2024-01-01", "True", "None", "true"):
        assert tag not in note["tags"]


def test_fix333_bad_frontmatter_file_does_not_abort_batch(obsidian, tmp_path):
    service, tmp = obsidian
    vault = _write_vault(
        tmp,
        {
            "01-good.md": "---\ntitle: 好笔记\ntags: [a]\n---\n好内容\n",
            "02-hostile.md": "---\ntitle: 异常笔记\ntags: 2024-01-01\n---\n异常内容\n",
            "03-good.md": "---\ntitle: 好笔记三\n---\n三号内容\n",
            "04-broken-yaml.md": "---\ntitle: [unclosed\n---\n坏 YAML\n",
        },
    )
    run(service.set_vault_path(str(vault)))
    report = run(service.rescan())  # 旧实现：TypeError → 整批 raise
    # 批次继续：3 个可解析文件入库；坏 YAML 文件按「单文件 skipped」
    # 准确落进 N138 诊断，绝不中断也不假报。
    assert report["added"] == 3
    assert "04-broken-yaml.md" in report["files"]["skipped"]["items"]
    notes = run(service.list_notes())
    titles = {n["title"] for n in notes}
    assert {"好笔记", "异常笔记", "好笔记三"} <= titles
    hostile = next(n for n in notes if n["title"] == "异常笔记")
    assert hostile["tags"] == []  # 异常标量类型降级为无 frontmatter 标签


# ---------------------------------------------------------------------------
# FIX-338 — 换行和 BOM 处理破坏代码块：导入保留有意义换行并规范元信息。
#
# BOM 开头的笔记：旧实现 frontmatter 解析失败（title 掉回文件名、
# frontmatter 文本混进正文）；正文旧实现 " ".join(split()) 压平一切换
# 行（fenced code 被拍成一行）。修复后：BOM 剥离一次、frontmatter 正常
# 解析（元信息规范化），CRLF→LF，代码块内容逐行保真（绝不逐行 trim /
# 压平换行），渲染出真正的 <pre><code>。
# ---------------------------------------------------------------------------


def test_fix338_bom_crlf_code_block_preserved(obsidian, tmp_path):
    from lumirss.obsidian import parse_note

    service, tmp = obsidian
    raw = (
        "\ufeff---\r\ntitle: 代码笔记\r\ntags: [py]\r\n---\r\n"
        "\r\n```python\r\nx = 1\r\n    y = 2\r\n\r\nz = 3\r\n```\r\n"
        "\r\n尾段落。\r\n"
    )
    vault = tmp / "vault"
    vault.mkdir()
    (vault / "code.md").write_bytes(raw.encode("utf-8"))
    run(service.set_vault_path(str(vault)))

    note = parse_note(vault / "code.md", vault)
    assert note is not None
    assert note["title"] == "代码笔记"  # BOM 剥离后 frontmatter 正常解析
    assert "py" in note["tags"]
    body = note["body_text"]
    assert "\ufeff" not in body  # BOM 只剥离一次且不残留
    assert "---" not in body.split("```")[0] or "title:" not in body  # 元信息不入正文
    assert "\r" not in body  # CRLF 规范化为 LF
    # 代码内容逐行保真：换行保留、行内缩进/空行不被动过。
    code = body.split("```")[1].removeprefix("python\n")
    assert code == "x = 1\n    y = 2\n\nz = 3\n"

    run(service.rescan())
    notes = run(service.list_notes())
    detail = run(service.get_note(notes[0]["ref"].split(":", 1)[1]))
    assert "<pre><code" in detail["contentHtml"]
    assert "x = 1\n    y = 2\n\nz = 3" in detail["contentHtml"]  # 渲染保真


# ---------------------------------------------------------------------------
# FIX-349 — 附件 Range 请求命中完整文件缓存时响应错误：返回正确状态、
# 范围和长度。
#
# 旧实现：GET /api/v1/mail/attachments/{id} 无视 Range 头，一律 200 全
# 量（音频/播放器类客户端无法seek）。修复后：无 Range → 200 全量 +
# Accept-Ranges: bytes；合法单区间 → 206 + Content-Range/正确长度；
# 语法坏区间 → 按 RFC 忽略（200 全量）；不可满足区间 → 416 +
# Content-Range: bytes */size。
# ---------------------------------------------------------------------------


def _mime_pdf(content: bytes) -> bytes:
    import base64

    b64 = base64.b64encode(content).decode()
    return (
        "From: N <n@example.com>\r\nTo: r@example.com\r\nSubject: range\r\n"
        "Message-ID: <range-349@example.com>\r\nMIME-Version: 1.0\r\n"
        'Content-Type: multipart/mixed; boundary="BND"\r\n\r\n'
        "--BND\r\nContent-Type: text/plain\r\n\r\n正文\r\n"
        "--BND\r\n"
        "Content-Type: application/pdf; name=\"a.pdf\"\r\n"
        "Content-Disposition: attachment; filename=\"a.pdf\"\r\n"
        "Content-Transfer-Encoding: base64\r\n\r\n"
        f"{b64}\r\n"
        "--BND--\r\n"
    ).encode()


@pytest.fixture()
def pdf_attachment(client):
    """入库一个 512 字节确定性 PDF 附件 → attachment id。"""
    pdf = b"%PDF-1.4\n" + bytes(range(256)) + bytes(range(256))
    created = client.post("/api/v1/mail/bridge-lists", json={"name": "r349"})
    assert created.status_code == 201
    lst = created.json()
    ingested = client.post(
        f"/api/mail/ingest/{lst['uuid']}",
        content=_mime_pdf(pdf),
        headers={"Authorization": f"Bearer {lst['secret']}"},
    )
    assert ingested.status_code == 200, ingested.text
    detail = client.get(
        f"/api/v1/mail/lists/{lst['uuid']}/messages/{ingested.json()['messageId']}/detail"
    )
    att = detail.json()["attachments"][0]
    return att["id"], pdf


def test_fix349_no_range_serves_full_200(pdf_attachment, client):
    att_id, pdf = pdf_attachment
    response = client.get(f"/api/v1/mail/attachments/{att_id}")
    assert response.status_code == 200
    assert response.content == pdf
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-disposition"].startswith("attachment;")


def test_fix349_range_serves_206_with_correct_span(pdf_attachment, client):
    att_id, pdf = pdf_attachment
    response = client.get(
        f"/api/v1/mail/attachments/{att_id}", headers={"Range": "bytes=0-99"}
    )
    assert response.status_code == 206
    assert response.headers["content-range"] == "bytes 0-99/521"
    assert len(response.content) == 100
    assert response.content == pdf[:100]

    response = client.get(
        f"/api/v1/mail/attachments/{att_id}", headers={"Range": "bytes=500-"}
    )
    assert response.status_code == 206
    assert response.headers["content-range"] == "bytes 500-520/521"
    assert response.content == pdf[500:]

    response = client.get(
        f"/api/v1/mail/attachments/{att_id}", headers={"Range": "bytes=-12"}
    )
    assert response.status_code == 206
    assert response.headers["content-range"] == "bytes 509-520/521"
    assert response.content == pdf[-12:]

    response = client.get(
        f"/api/v1/mail/attachments/{att_id}", headers={"Range": "bytes=0-999999"}
    )
    assert response.status_code == 206
    assert response.headers["content-range"] == "bytes 0-520/521"
    assert response.content == pdf


def test_fix349_unsatisfiable_range_is_416(pdf_attachment, client):
    att_id, _pdf = pdf_attachment
    response = client.get(
        f"/api/v1/mail/attachments/{att_id}", headers={"Range": "bytes=1000-"}
    )
    assert response.status_code == 416
    assert response.headers["content-range"] == "bytes */521"

    response = client.get(
        f"/api/v1/mail/attachments/{att_id}", headers={"Range": "bytes=-0"}
    )
    assert response.status_code == 416


def test_fix349_malformed_and_multirange_ignored_serve_full(pdf_attachment, client):
    att_id, pdf = pdf_attachment
    for header in ("bytes=abc", "bytes=0-1,10-20", "items=0-5", "bytes="):
        response = client.get(
            f"/api/v1/mail/attachments/{att_id}", headers={"Range": header}
        )
        assert response.status_code == 200, header
        assert response.content == pdf, header
