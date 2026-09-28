"""FIX-148 — 浏览器语音 vs 服务端可导出音频的能力区分（诚实口径）。

两种 TTS 能力必须被各能力面如实区分，不得混淆宣称：

1. 浏览器语音（Web Speech，P18 朗读引擎）：客户端本机合成，文本不出
   设备——服务端视角=无外发（data-flows: configured=false + local=true），
   且服务端合成端点在未配置 provider 时必须 409 tts_not_configured
   （N098 既有契约）——没有任何端点在无 provider 时宣称可产出音频；
2. 服务端合成（purpose=tts 的 OpenAI 兼容 /audio/speech，N098/N099
   导出链路机械）：朗读文本经 BFF 外发给所配置 provider——能力面必须
   如实披露外发主机（configured=true + providerHost 仅主机名 + local=false）。
   N099「可导出听读音频」本身仍凭证阻塞，此处只验证区分诚实，不伪造能力。

N181 data-flows 是唯一的服务端 TTS 能力/外发披露面；旧行为把 tts 一律
硬编码成「恒为本机」——provider 已配置时仍是谎言（本文件先红后绿）。
"""

import secrets as _secrets

FAKE_KEY = "sk-" + _secrets.token_urlsafe(12)


def _flows_of(client):
    body = client.get("/api/v1/privacy/data-flows")
    assert body.status_code == 200, body.text
    return {item["capability"]: item for item in body.json()["flows"]}


def test_unconfigured_tts_is_local_browser_speech_and_no_exportable_claim(
    client, monkeypatch
):
    """未配置 purpose=tts provider：浏览器本机语音（无外发）+ 合成端点
    诚实 409——没有任何面宣称服务端可产出/导出音频。"""
    monkeypatch.delenv("AI_API_KEY", raising=False)

    flows = _flows_of(client)
    tts = flows["tts"]
    assert tts["configured"] is False, "未配置 provider 时不得宣称服务端合成外发"
    assert tts["local"] is True, "未配置 provider 时 TTS=浏览器本机语音"
    assert not tts.get("providerHost")

    # 跨面一致：同一"未配置"判定下，合成端点不假装能产出音频。
    response = client.post("/api/v1/tts/synthesize", json={"text": "第一句话"})
    assert response.status_code == 409, response.text
    assert response.json()["error"]["type"] == "tts_not_configured"


def test_configured_tts_discloses_provider_egress_host_only(client, monkeypatch):
    """配置了 purpose=tts（默认链：baseUrl+model+key 齐全）：能力面必须
    如实披露外发给该 provider 主机——不再是「恒为本机」的谎言。"""
    monkeypatch.delenv("AI_API_KEY", raising=False)
    put = client.put(
        "/api/v1/settings/ai",
        json={"baseUrl": "https://tts.example.com/v1", "model": "tts-1"},
    )
    assert put.status_code == 200, put.text
    key = client.put("/api/v1/settings/ai/key", json={"value": FAKE_KEY})
    assert key.status_code == 204, key.text

    body = client.get("/api/v1/privacy/data-flows")
    assert body.status_code == 200
    flows = {item["capability"]: item for item in body.json()["flows"]}
    tts = flows["tts"]
    assert tts["configured"] is True, "provider 已配置（与 /tts/synthesize 同一判定）"
    assert tts["local"] is False
    assert tts["providerHost"] == "tts.example.com"  # 仅主机名
    assert FAKE_KEY not in str(body.json()), "绝无密钥值"
