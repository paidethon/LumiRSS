"""FIX-157 — 邮件、API 来源导入的 HTML / 附件名 / 日期解析健壮性。

真实修复面：API 来源导入的日期解析（``atom_render.rfc3339``）。JSON
API 普遍以 epoch 秒 / epoch 毫秒数字或 RFC 2822 字符串声明时间；此前
只接受 ISO 字符串，非 ISO 一律 None → 条目时间退化为来源 created_at
（同一来源所有条目同一时刻——排序信息丢失，这是「日期解析错误」）。

合成授权数据：全部时间戳/邮件样本为本测试合成的无凭据数据。
"""

import email.message
import email.policy

from lumirss.api_sources import _entry_timing
from lumirss.atom_render import rfc3339

# ---- rfc3339：数字 epoch（秒 / 毫秒）---------------------------------------


def test_epoch_seconds_number_normalized():
    assert rfc3339(1727415600) == "2024-09-27T05:40:00+00:00"


def test_epoch_seconds_float_normalized():
    assert rfc3339(1727415600.0) == "2024-09-27T05:40:00+00:00"


def test_epoch_millis_number_normalized():
    assert rfc3339(1727415600000) == "2024-09-27T05:40:00+00:00"


def test_epoch_out_of_plausible_range_is_none():
    # 1e6「秒」是 1972 年——不是 API 来源的合理声明时间；负数同理。
    assert rfc3339(1_000_000) is None
    assert rfc3339(-1727415600) is None
    assert rfc3339(10**15) is None  # 超出秒/毫秒两种量级约定


def test_epoch_bool_is_none():
    # bool 是 int 的子类——True/False 绝不能被当成 epoch。
    assert rfc3339(True) is None
    assert rfc3339(False) is None


# ---- rfc3339：RFC 2822 字符串（邮件/传统 API 的常见形态）--------------------


def test_rfc2822_gmt_normalized():
    assert rfc3339("Fri, 27 Sep 2024 05:40:00 GMT") == "2024-09-27T05:40:00+00:00"


def test_rfc2822_with_offset_normalized():
    assert (
        rfc3339("Tue, 01 Oct 2026 08:00:00 +0800") == "2026-10-01T00:00:00+00:00"
    )


# ---- 既有契约不回归：ISO / 垃圾输入 ---------------------------------------


def test_iso_strings_and_garbage_unchanged():
    assert rfc3339("2024-09-27T05:40:00Z") == "2024-09-27T05:40:00+00:00"
    assert rfc3339("2024-09-27T07:40:00+02:00") == "2024-09-27T05:40:00+00:00"
    assert rfc3339("  2024-09-27T05:40:00+00:00  ") == "2024-09-27T05:40:00+00:00"
    assert rfc3339("not-a-date") is None
    assert rfc3339("") is None
    assert rfc3339(None) is None
    assert rfc3339([]) is None


# ---- 端到端：_entry_timing 用数字 epoch 声明的条目不再退化 ------------------


def test_entry_timing_accepts_epoch_millis():
    published, updated = _entry_timing(
        1727415600000,
        stable_fallback="2026-01-01T00:00:00+00:00",
        now_epoch=1780000000.0,
    )
    assert published == "2024-09-27T05:40:00+00:00"
    assert updated == "2024-09-27T05:40:00+00:00"


def test_entry_timing_garbage_still_falls_back_to_stable_anchor():
    published, updated = _entry_timing(
        "垃圾日期",
        stable_fallback="2026-01-01T00:00:00+00:00",
        now_epoch=1780000000.0,
    )
    assert published is None
    assert updated == "2026-01-01T00:00:00+00:00"


# ---- 邮件腿守卫：RFC 2231 编码附件名解出真名；HTML 过净化边界 --------------


def _mail_with_attachment() -> email.message.EmailMessage:
    msg = email.message.EmailMessage(policy=email.policy.default)
    msg["Subject"] = "附件名解码"
    msg["From"] = "sender@example.com"
    msg["To"] = "inbox@example.com"
    msg.set_content("正文")
    msg.add_attachment(
        b"%PDF-1.4 synthetic",
        maintype="application",
        subtype="pdf",
        filename="年度报告.pdf",
    )
    return msg


def test_email_attachment_filename_decodes_rfc2231():
    from lumirss.mail_bridge import _process_attachments

    meta, stored = _process_attachments(_mail_with_attachment())
    assert len(meta) == 1
    # RFC 2231/RFC 2047 编码的中文附件名必须解出真名，而不是裸编码串。
    assert meta[0]["filename"] == "年度报告.pdf"
    assert stored and stored[0]["filename"] == "年度报告.pdf"


def test_email_html_body_passes_sanitize_boundary():
    from lumirss.mail_sanitize import sanitize_email_html

    dirty = '<p>你好<script>alert(1)</script><img src="https://x.example/pixel.png"></p>'
    clean = sanitize_email_html(dirty)
    assert "<script" not in clean.lower()
    assert "你好" in clean
