"""NEW-381..390 共享种子助手 —— 离线（无网络）构造各成员的资料。

剪藏不能走 /library/clips（按设计强制服务端抓取），测试用
ClipStore + user_context 直接落到目标成员的 per-user 库。
"""

import asyncio
import uuid as _uuid

from lumirss.user_scope import user_context


def seed_clip(env, who: str, *, url: str, title: str, html: str) -> str:
    """向目标成员的库写入一条剪藏，返回 item uuid。"""
    from lumirss.library_clips import ClipStore

    user_id = env[who]["userId"]

    async def run():
        with user_context(user_id):
            await env["app"].state.db.migrate()
            view, _created = await ClipStore(env["app"].state.db).create_clip(
                url=url,
                title=title,
                content_html=html,
                content_text="占位正文",
            )
        return view.ref.split(":", 1)[1]

    return asyncio.run(run())


def new_uuid() -> str:
    return str(_uuid.uuid4())


ZOTERO_RDF = """<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
 xmlns:dc="http://purl.org/dc/elements/1.1/"
 xmlns:dcterms="http://purl.org/dc/terms/"
 xmlns:bibo="http://purl.org/ontology/bibo/"
 xmlns:z="http://www.zotero.org/namespaces/export#"
 xmlns:foaf="http://xmlns.com/foaf/0.1/">
 <foaf:Person rdf:about="http://www.zotero.org/namespaces/export#author-1">
  <foaf:surname>陈</foaf:surname>
  <foaf:givenName>静</foaf:givenName>
 </foaf:Person>
 <z:item rdf:about="http://www.zotero.org/zotero/items/ABCD1234">
  <rdf:type resource="http://purl.org/ontology/bibo/AcademicArticle"/>
  <dc:title>长期保存的格式迁移研究</dc:title>
  <dc:creator rdf:resource="http://www.zotero.org/namespaces/export#author-1"/>
  <dc:date>2024-03-01</dc:date>
  <dcterms:abstract>讨论书目记录的长期保存与格式互通。</dcterms:abstract>
  <dc:identifier>https://journal.example/pres-2024</dc:identifier>
  <bibo:doi>10.1000/pres.2024</bibo:doi>
  <dc:subject>数字保存</dc:subject>
  <dc:subject>互操作</dc:subject>
  <dc:source>档案学刊</dc:source>
  <dc:publisher>档案出版社</dc:publisher>
  <z:itemType>journalArticle</z:itemType>
  <bibo:pages>12-31</bibo:pages>
 </z:item>
 <z:item rdf:about="http://www.zotero.org/zotero/items/EFGH5678">
  <dc:title>第二份书目</dc:title>
  <dc:creator>李四</dc:creator>
  <dc:date>2023</dc:date>
  <dc:identifier>https://books.example/two</dc:identifier>
 </z:item>
</rdf:RDF>
"""

RIS_SAMPLE = """TY  - JOUR
AN  - ris-key-001
TI  - 引文往返校验初探
AU  - 王五
AU  - 赵六
PY  - 2022
T2  - 情报学报
PB  - 情报出版社
UR  - https://journal.example/ris-2022
DO  - 10.2000/ris.2022
KW  - RIS
KW  - 往返校验
AB  - 讨论导出后的往返校验方法。
CN  - 11-1000/G2
SN  - 1000-0000
ER  -

TY  - BOOK
TI  - 第二条书目
AU  - 作者甲
PY  - 2021
ER  -
"""


def warc_record(headers: dict[str, str], payload: bytes) -> bytes:
    head = "WARC/1.0\r\n" + "".join(
        f"{key}: {value}\r\n" for key, value in headers.items()
    )
    head += f"Content-Length: {len(payload)}\r\n\r\n"
    return head.encode("utf-8") + payload + b"\r\n\r\n"


def sample_warc() -> bytes:
    html_body = "<html><body><h1>网页标题</h1><p>正文段落</p></body></html>".encode()
    html_payload = (
        b"HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\n\r\n" + html_body
    )
    text_payload = (
        b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n\r\n"
        b"\xe7\xba\xaf\xe6\x96\x87\xe6\x9c\xac\xe6\xad\xa3\xe6\x96\x87"  # 纯文文本正文
    )
    active_payload = (
        b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n"
        b"<html><body><script>alert(1)</script><p>x</p></body></html>"
    )
    return (
        warc_record(
            {
                "WARC-Type": "response",
                "WARC-Target-URI": "https://archive.example/page-1",
                "WARC-Record-ID": "<urn:uuid:11111111-1111-4111-8111-111111111111>",
                "WARC-Date": "2026-01-05T00:00:00Z",
                "WARC-Payload-Digest": "sha1:AAAA1111",
                "Content-Type": "application/http; msgtype=response",
            },
            html_payload,
        )
        + warc_record(
            {
                "WARC-Type": "response",
                "WARC-Target-URI": "https://archive.example/notes.txt",
                "WARC-Record-ID": "<urn:uuid:22222222-2222-4222-8222-222222222222>",
                "WARC-Payload-Digest": "sha1:BBBB2222",
                "Content-Type": "application/http; msgtype=response",
            },
            text_payload,
        )
        + warc_record(
            {
                "WARC-Type": "response",
                "WARC-Target-URI": "https://archive.example/active.html",
                "WARC-Record-ID": "<urn:uuid:33333333-3333-4333-8333-333333333333>",
                "Content-Type": "application/http; msgtype=response",
            },
            active_payload,
        )
        + warc_record(
            {
                "WARC-Type": "metadata",
                "WARC-Target-URI": "https://archive.example/meta",
                "Content-Type": "application/warc-fields",
            },
            b"outlink: https://archive.example/page-1\r\n",
        )
    )
