"""R2 BFF8 — import/attachment/export 域 FIX 项的行为证据。

每个测试编码对应 FIX 项的验收规则；实现已满足规则的，通过的测试即
BASELINE_OK 核验证据（BASELINE 标注）；实现不满足的先以失败复现再修。

覆盖：FIX-321（向导 zip 导入纯内存腿）、FIX-322（附件内容嗅探）、
FIX-323（同名附件共存）、FIX-325（批次重试幂等）、FIX-330（导入报告
跳过不冒充新增 + 原行可定位）。全部凭据/内容为运行时生成的假数据。
"""

import asyncio
import io
import json
import zipfile

from lumirss.import_batch_store import ImportBatchStore
from lumirss.itemref import new_library_uuid
from lumirss.lumi_data_wizard import (
    WIZARD_KIND,
    WIZARD_SCHEMA,
    WizardImportError,
    parse_import_zip,
)
from lumirss.lumi_notes import LumiNotesStore
from lumirss.mail_bridge import _process_attachments
from lumirss.main import app
from lumirss.tags import TagStore


def run(coroutine):
    return asyncio.run(coroutine)


# ---------------------------------------------------------------------------
# FIX-321 — zip 导入越界路径/符号链接（lumi-data 向导腿）。
#
# restore 归档腿（磁盘解压）由 tests/test_archive_safety.py 覆盖
# （traversal/绝对路径/盘符/符号链接/重复成员/炸弹 + 本批新增的多段
# `../../evil.txt` 用例）。向导腿的属性不同：parse_import_zip 是逐成员
# 内存读取，从不做磁盘解压——这里把该性质固化为测试。


def _wizard_zip(extra_members: list[tuple[str, bytes]]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "manifest.json",
            json.dumps(
                {
                    "schema": WIZARD_SCHEMA,
                    "kind": WIZARD_KIND,
                    "components": {"tags": 1},
                }
            ),
        )
        archive.writestr(
            "tags.json",
            json.dumps(
                {
                    "available": True,
                    "items": [],
                    "bindings": [{"tag": "t", "itemRefs": []}],
                }
            ),
        )
        for name, data in extra_members:
            archive.writestr(name, data)
    return buffer.getvalue()


def test_fix321_wizard_import_zip_in_memory_no_disk_extraction(tmp_path, monkeypatch):
    """敌意成员名（越界/绝对路径）既不落盘也不进入组件解析：向导导入
    只按白名单键内存读取，磁盘沙箱零写入（BASELINE_OK）。"""
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    monkeypatch.chdir(sandbox)
    payload = _wizard_zip(
        [
            ("../../evil.txt", b"hostile"),
            ("/etc/evil.json", b"{}"),
            ("a/../../evil2.txt", b"hostile"),
        ]
    )
    components = parse_import_zip(payload)
    # 只有白名单组件被识别；未知/越界成员名被忽略。
    assert set(components) == {"tags"}
    assert components["tags"]["bindings"] == [{"tag": "t", "itemRefs": []}]
    # 性质：整个流程对文件系统零写入（逐成员 archive.read 内存读取，
    # 无 extractall/extract 调用点——见 lumi_data_wizard.parse_import_zip）。
    assert list(sandbox.iterdir()) == []
    assert not list(tmp_path.rglob("evil*"))


def test_fix321_wizard_import_zip_symlink_member_ignored(tmp_path, monkeypatch):
    """符号链接属性成员同样不落盘（内存读取路径根本不创建文件）。"""
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    monkeypatch.chdir(sandbox)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "manifest.json",
            json.dumps({"schema": WIZARD_SCHEMA, "kind": WIZARD_KIND}),
        )
        info = zipfile.ZipInfo("link.json")
        info.external_attr = 0o120777 << 16
        info.create_system = 3
        archive.writestr(info, "{}")
    # "link" 不在组件白名单 → 无可识别组件，解析干净拒绝；即便成员名
    # 伪装成白名单键，内存读取路径也不会创建任何文件。
    try:
        parse_import_zip(buffer.getvalue())
    except WizardImportError:
        pass
    else:
        raise AssertionError("symlink-only package should not parse as a component set")
    assert list(sandbox.iterdir()) == []


# ---------------------------------------------------------------------------
# FIX-322 — 附件只看扩展名/声明 MIME 不核对实际类型 → 内容嗅探。


def _mail_with_attachments(*attachments: tuple[str, str, bytes]):
    """构造一封带附件的邮件消息（filename/mime/bytes）。"""
    import email.message
    import email.utils

    message = email.message.EmailMessage()
    message["From"] = "sender@example.com"
    message["To"] = "list@example.com"
    message["Subject"] = "attachments"
    message["Date"] = email.utils.formatdate()
    message.set_content("body")
    for filename, mime, content in attachments:
        maintype, _, subtype = mime.partition("/")
        message.add_attachment(
            content, maintype=maintype, subtype=subtype, filename=filename
        )
    return message


def test_fix322_html_renamed_png_rejected_with_reason():
    """HTML 内容改名 .png 并声明 image/png → 嗅探拒绝并给出原因。"""
    html = b"<!DOCTYPE html><html><body><script>alert(1)</script></body></html>"
    meta, stored = _process_attachments(
        _mail_with_attachments(("photo.png", "image/png", html))
    )
    assert stored == []
    assert len(meta) == 1
    assert meta[0]["status"] == "skipped_mismatch"
    assert "不一致" in meta[0]["reason"]


def test_fix322_real_png_passes():
    """真 PNG 魔法字节 + .png + image/png → 正常放行入库。"""
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    meta, stored = _process_attachments(
        _mail_with_attachments(("photo.png", "image/png", png))
    )
    assert len(stored) == 1
    assert meta[0]["status"] == "stored"
    assert meta[0]["mime"] == "image/png"


def test_fix322_pdf_and_office_magic_enforced():
    """pdf/office（OLE2/ZIP 容器）类型同样按魔法字节核对。"""
    meta, stored = _process_attachments(
        _mail_with_attachments(("doc.pdf", "application/pdf", b"not-a-pdf" + b"\x00" * 32))
    )
    assert stored == []
    assert meta[0]["status"] == "skipped_mismatch"
    real_docx = b"PK\x03\x04" + b"\x00" * 64
    meta, stored = _process_attachments(
        _mail_with_attachments(
            (
                "doc.docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                real_docx,
            )
        )
    )
    assert len(stored) == 1
    assert meta[0]["status"] == "stored"


def test_fix322_html_renamed_txt_with_html_mime_rejected():
    """HTML 内容改 .txt 声明 text/html（宽容文本腿放行的形状）→ 嗅探
    按 HTML 标记拒绝，不把 HTML 当文本嵌入。"""
    html = b"<html><body>x</body></html>"
    meta, stored = _process_attachments(
        _mail_with_attachments(("note.txt", "text/html", html))
    )
    assert stored == []
    assert meta[0]["status"] == "skipped_mismatch"


def test_fix322_plain_text_still_passes():
    meta, stored = _process_attachments(
        _mail_with_attachments(("note.txt", "text/plain", "普通文本内容".encode()))
    )
    assert len(stored) == 1
    assert meta[0]["status"] == "stored"


# ---------------------------------------------------------------------------
# FIX-323 — 同名附件共存：独立对象 ID + 原始文件名保留（BASELINE_OK：
# mail_attachments 以 uuid4 为主键、filename 只是元数据）。


def test_fix323_same_name_attachments_both_kept_by_ingest():
    """ingest 层：两个同名附件都进入待落库清单，原文件名各自保留。"""
    filename = "notes.txt"
    meta, stored = _process_attachments(
        _mail_with_attachments(
            (filename, "text/plain", b"first content"),
            (filename, "text/plain", b"second content"),
        )
    )
    assert [s["content"] for s in stored] == [b"first content", b"second content"]
    assert len(meta) == 2
    assert meta[0]["filename"] == filename
    assert meta[1]["filename"] == filename


def test_fix323_attachment_store_rows_unique_per_attachment(client):
    """落库层：同一封邮件两个同名附件 → 两行、两个独立 uuid、原文件名
    保留、各自内容可读（后一个不覆盖前一个）。"""
    from lumirss.db_tx import transaction
    from lumirss.mail_attachments import MailAttachmentStore

    async def scenario():
        db = app.state.db
        await db.migrate()
        store = MailAttachmentStore(db)

        def _tx(conn):
            id1 = store.save(
                conn,
                list_uuid="list-fix323",
                message_id="msg-fix323",
                filename="notes.txt",
                mime="text/plain",
                content=b"first",
            )
            id2 = store.save(
                conn,
                list_uuid="list-fix323",
                message_id="msg-fix323",
                filename="notes.txt",
                mime="text/plain",
                content=b"second",
            )
            return id1, id2

        id1, id2 = await transaction(db, _tx)
        assert id1 != id2
        rows = await store.list_for_message("list-fix323", "msg-fix323")
        assert len(rows) == 2
        assert {str(r["filename"]) for r in rows} == {"notes.txt"}
        first = await store.get(id1)
        second = await store.get(id2)
        assert bytes(first["content"]) == b"first"
        assert bytes(second["content"]) == b"second"

    run(scenario())


# ---------------------------------------------------------------------------
# FIX-325 — 导入批次重试幂等（BASELINE_OK：只重试失败项 + 已存在记
# skipped；同批幂等记录（retryPayload）随批次落库可恢复）。


def test_fix325_retry_only_failed_items_no_duplicates(client):
    """3 项导入 1 项失败 → 批次 retryPayload 只含失败项；重试仅创建 1，
    总数 3、无重复；再次重试 0 新增（幂等）。"""

    async def seed():
        db = app.state.db
        await db.migrate()
        notes = LumiNotesStore(db)
        # 前两项已成功导入。
        await notes.import_note(name="a.md", content="A", workspace_id=None)
        await notes.import_note(name="b.md", content="B", workspace_id=None)
        # 批次记录：3 项中 1 项失败（retry_payload 只存失败项）。
        return await ImportBatchStore(db).record(
            kind="md_notes",
            counts={"imported": 2, "skipped": 0, "failed": 1},
            errors=[{"url": "c.md", "reason": "boom"}],
            retry_payload=[{"name": "c.md", "content": "C", "workspaceId": None}],
        )

    batch_id = run(seed())

    first = client.post(f"/api/v1/library/import-batches/{batch_id}/retry")
    assert first.status_code == 200, first.text
    assert first.json()["imported"] == 1
    assert first.json()["skipped"] == 0
    second = client.post(f"/api/v1/library/import-batches/{batch_id}/retry")
    # 原批次 retryPayload 仍可恢复（幂等记录落库），重放只记 skipped。
    assert second.status_code == 200, second.text
    assert second.json()["imported"] == 0
    assert second.json()["skipped"] == 1

    async def count_notes():
        db = app.state.db
        dupes = await db.fetch_all(
            "SELECT content_hash, COUNT(*) AS n FROM lumi_notes GROUP BY content_hash HAVING n > 1"
        )
        total = await db.fetch_one("SELECT COUNT(*) AS n FROM lumi_notes")
        return list(dupes), int(total["n"])

    dupes, total = run(count_notes())
    assert dupes == []
    assert total == 3


# ---------------------------------------------------------------------------
# FIX-330 — 导入报告：跳过不冒充新增；结果按新增/跳过/失败分别计数
# 且可定位原行。


def test_fix330_wizard_tags_import_counts_existing_bindings_as_skipped(client):
    """已存在的绑定（attach 幂等原样返回）按 skipped 计数并给出
    (tag, itemRef) 原行定位，不再计入 added。"""
    ref_existing = f"library:{new_library_uuid()}"
    ref_new = f"library:{new_library_uuid()}"

    async def prebind():
        db = app.state.db
        await db.migrate()
        await TagStore(db).attach(ref_existing, "已有标签")

    run(prebind())

    async def apply():
        db = app.state.db
        components = {
            "tags": {
                "available": True,
                "items": [],
                "bindings": [
                    {"tag": "已有标签", "itemRefs": [ref_existing, ref_new]}
                ],
            }
        }
        from lumirss.lumi_data_wizard import apply_import

        return await apply_import(db, {"components": components}, ["tags"])

    tags = run(apply())["components"]["tags"]
    assert tags["added"] == 1  # 只有 ref_new 是真新增
    assert tags["skipped"] == 1  # ref_existing 已存在——不再冒充新增
    assert {"tag": "已有标签", "itemRef": ref_existing} in tags["skippedRows"]


def test_fix330_wizard_tags_roundtrip_reports_all_skipped(client):
    """导出→导入 roundtrip：全部绑定已存在 → added == 0、skipped == N。"""
    refs = [f"library:{new_library_uuid()}" for _ in range(3)]

    async def prebind():
        db = app.state.db
        await db.migrate()
        store = TagStore(db)
        for ref in refs:
            await store.attach(ref, "循环标签")

    run(prebind())

    async def apply():
        db = app.state.db
        components = {
            "tags": {
                "available": True,
                "items": [],
                "bindings": [{"tag": "循环标签", "itemRefs": list(refs)}],
            }
        }
        from lumirss.lumi_data_wizard import apply_import

        return await apply_import(db, {"components": components}, ["tags"])

    tags = run(apply())["components"]["tags"]
    assert tags["added"] == 0
    assert tags["skipped"] == 3
    assert len(tags["skippedRows"]) == 3
