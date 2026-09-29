"""FIX-364 — 文件响应过早关闭句柄（流读取生命周期覆盖完整传输）。

判定：BASELINE_OK。逐点核对后，BFF 当前不存在任何
StreamingResponse-over-file-handle 的下载路径（全仓
``grep StreamingResponse`` 仅 agent.py SSE 一处；其余全部为
``Response(content=bytes)``）：zip 导出（lumi_data_wizard /
research_pack_zip）在 BytesIO 上构建并整体物化为 bytes，附件下载
（mail_attachments ≤5MB、快照 page.html、TTS 音频）也先完整读出再
构造响应。bytes 对象与请求作用域没有任何上下文管理器绑定，「路由
函数返回后句柄提前关闭」这一缺陷类在结构上不存在。

本文件是验证性证据（BASELINE_OK 判定的通过即证据）：
1. 附件下载：慢消费迭代器（4096B 切片 + 消费节奏暂停）完整读完
   整个传输，sha256 与入库字节一致、Content-Length 与存储 size 一致；
2. zip 导出：慢消费下传输完整完成，下载体在路由函数早已返回之后
   仍可整体解析（zipfile 合法 + manifest.json 可读）——证明响应体
   生命周期覆盖完整传输，慢客户端拿到的文件校验一致。

全部凭据/内容为运行期伪造（确定性 PRNG 种子），无真实秘密。
"""

import hashlib
import io
import hashlib
import time
import zipfile


def _deterministic_payload(size: int, seed: int) -> bytes:
    # %PDF- 头满足 FIX-322 附件内容嗅探（.pdf 必须带魔法字节）。
    # 确定性字节流由 sha256 派生（可复现校验和所需），不使用随机数源。
    stream = hashlib.sha256(f"lumi-fix364-{seed}".encode()).digest()
    while len(stream) < size:
        stream += hashlib.sha256(stream[-32:]).digest()
    return b"%PDF-1.4\n" + stream[:size]


def _bridge_list(client, name: str) -> dict:
    created = client.post("/api/v1/mail/bridge-lists", json={"name": name})
    assert created.status_code == 201, created.text
    return created.json()


def _mime_with_attachment(filename: str, mime: str, content: bytes) -> bytes:
    import base64

    b64 = base64.b64encode(content).decode()
    return (
        "From: Newsletter <news@example.com>\r\n"
        "To: reader@example.com\r\n"
        "Subject: FIX-364\r\n"
        "Message-ID: <fix364@example.com>\r\n"
        "MIME-Version: 1.0\r\n"
        'Content-Type: multipart/mixed; boundary="BND"\r\n'
        "\r\n"
        "--BND\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n正文\r\n"
        f"--BND\r\nContent-Type: {mime}; name=\"{filename}\"\r\n"
        f"Content-Disposition: attachment; filename=\"{filename}\"\r\n"
        f"Content-Transfer-Encoding: base64\r\n\r\n{b64}\r\n"
        "--BND--\r\n"
    ).encode()


def test_attachment_download_slow_consumer_receives_checksum_identical_file(client):
    """慢消费迭代器读完完整传输：sha256/长度与入库字节一致。

    消费节奏（每片暂停）模拟慢客户端；响应体是路由函数返回前已
    完整物化的 bytes——传输期间没有任何可提前关闭的文件句柄。"""
    payload = _deterministic_payload(300_000, seed=364)
    expected_sha = hashlib.sha256(payload).hexdigest()

    lst = _bridge_list(client, "FIX-364 附件")
    ingested = client.post(
        f"/api/mail/ingest/{lst['uuid']}",
        content=_mime_with_attachment("big.pdf", "application/pdf", payload),
        headers={"Authorization": f"Bearer {lst['secret']}"},
    )
    assert ingested.status_code == 200, ingested.text
    detail = client.get(
        f"/api/v1/mail/lists/{lst['uuid']}/messages/"
        f"{ingested.json()['messageId']}/detail"
    )
    attachment = detail.json()["attachments"][0]
    assert attachment["size"] == len(payload)

    chunks = []
    with client.stream(
        "GET", f"/api/v1/mail/attachments/{attachment['id']}"
    ) as response:
        assert response.status_code == 200
        assert int(response.headers["content-length"]) == len(payload)
        # 慢消费：小切片 + 逐片暂停——传输必须支撑任意消费节奏。
        for chunk in response.iter_raw(chunk_size=4096):
            chunks.append(chunk)
            time.sleep(0.0005)

    received = b"".join(chunks)
    assert len(received) == len(payload)
    assert hashlib.sha256(received).hexdigest() == expected_sha


def test_zip_export_body_outlives_route_and_stays_parseable(client):
    """zip 导出：路由返回后（headers 收完、体仍在慢消费）响应体
    依旧完整可解析——BytesIO 物化的 bytes 与请求生命周期解耦，
    manifest.json 可读、成员计数与响应头一致。"""
    created = client.get("/api/v1/export/lumi-data.zip")
    assert created.status_code == 200, created.text
    declared_files = created.headers.get("x-manifest-files")

    chunks = []
    with client.stream("GET", "/api/v1/export/lumi-data.zip") as response:
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/zip"
        for chunk in response.iter_raw(chunk_size=2048):
            chunks.append(chunk)
            time.sleep(0.0005)

    received = b"".join(chunks)
    # 此时路由函数早已返回——zip 仍必须整体可解析（生命周期覆盖传输）。
    with zipfile.ZipFile(io.BytesIO(received)) as archive:
        names = archive.namelist()
        assert "manifest.json" in names
        manifest = __import__("json").loads(
            archive.read("manifest.json").decode("utf-8")
        )
        assert manifest["kind"] == "lumirss-lumi-data"
        file_count = sum(
            1 for name in names if name != "manifest.json"
        )
        if declared_files is not None:
            assert int(declared_files) == file_count
