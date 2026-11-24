"""AI/ML API 预设：设置面板里的具名聊天供应商（OpenAI 兼容，https://api.aimlapi.com/v1）。

覆盖：
  * 保存预设行 → openclaw.json 写出 aimlapi provider（固定根地址、默认模型、主模型路由）；
  * 根地址只认精确的 api.aimlapi.com，不能把 AI/ML API Key 带到别的主机；
  * 拉取模型走公开目录 /models?include=all（不带 Key），只保留 type=openai/chat-completions；
  * 拉取不跟随跳转，跳转目标拿不到任何凭据；
  * 已配置其他供应商、没碰预设的用户，配置零变化。

运行：pytest tests/test_aimlapi_preset.py -q
"""
from __future__ import annotations

import json
import sys
import urllib.request
import urllib.response
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "web"))
sys.path.insert(0, str(PROJECT_ROOT / "skills" / "shared" / "scripts"))

import web.app as web  # noqa: E402

BASE = "https://api.aimlapi.com/v1"
EXISTING = {
    "models": {"providers": {"openai": {"api": "openai-completions",
                                        "baseUrl": "https://api.deepseek.com/v1",
                                        "apiKey": "sk-deepseek-fake",
                                        "models": [{"id": "deepseek-chat"}]}}},
    "agents": {"defaults": {"model": {"primary": "openai/deepseek-chat"}}},
}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("EASEL_AGENT_RUNTIME", "openclaw")
    monkeypatch.setenv("EASEL_CHAT_TRANSPORT", "http")
    monkeypatch.setattr(web, "ENV_FILE", tmp_path / ".env")
    monkeypatch.setenv("EASEL_OPENCLAW_STATE_DIR", str(tmp_path))
    oc = tmp_path / "openclaw.json"
    oc.write_text(json.dumps(EXISTING), encoding="utf-8")
    monkeypatch.setattr(web, "_read_env", lambda: {})
    local = "http://127.0.0.1:7860"
    c = TestClient(web.app, base_url=local, client=("127.0.0.1", 51234), headers={"Origin": local})
    return c, oc


def _save(c, **kw):
    row = {"slot": "aimlapi", "name": "AI/ML API", "model": "", "baseUrl": BASE,
           "key": "sk-aiml-fake", "primary": True}
    row.update(kw)
    return c.post("/api/settings/models/save", json={"channel": "chat", "rows": [row]})


def test_save_writes_aimlapi_provider_and_primary(client):
    c, oc = client
    r = _save(c)
    assert r.status_code == 200, r.text
    data = json.loads(oc.read_text())
    prov = data["models"]["providers"]["aimlapi"]
    assert prov["baseUrl"] == BASE
    assert prov["apiKey"] == "sk-aiml-fake"
    assert prov["models"][0]["id"] == web.AIMLAPI_DEFAULT_MODEL
    assert "api" not in prov, "OpenAI 兼容：不写 api 字段，openclaw 默认 openai-completions"
    assert data["agents"]["defaults"]["model"]["primary"] == f"aimlapi/{web.AIMLAPI_DEFAULT_MODEL}"
    # 旧的 openai provider 原样保留
    assert data["models"]["providers"]["openai"] == EXISTING["models"]["providers"]["openai"]


def test_saved_preset_is_listed_as_named_row(client):
    c, _ = client
    assert _save(c, model="openai/gpt-4o-mini").status_code == 200
    rows = c.get("/api/settings/models").json()["channels"]["chat"]["rows"]
    row = next(r for r in rows if r.get("slot") == "aimlapi")
    assert row["name"] == "AI/ML API"
    assert row["baseUrl"] == BASE
    assert row["model"] == "openai/gpt-4o-mini"
    assert row["role"] == "主"
    assert "sk-aiml-fake" not in json.dumps(rows), "Key 不能明文回显"


@pytest.mark.parametrize("bad", [
    "https://evil.example.com/v1",
    "https://api.aimlapi.com.evil.example/v1",
    "https://aimlapi.com/v1",
    "http://api.aimlapi.com/v1",
])
def test_save_rejects_other_base_urls(client, bad):
    c, oc = client
    before = oc.read_text()
    r = _save(c, baseUrl=bad)
    assert r.status_code == 400, r.text
    assert "api.aimlapi.com/v1" in r.json()["detail"]
    assert oc.read_text() == before
    # 同一地址则放行：确认拒绝来自地址校验，而不是预设本身不可用
    assert _save(c).status_code == 200


def test_save_without_key_is_rejected_on_first_setup(client):
    c, oc = client
    before = oc.read_text()
    r = _save(c, key="")
    assert r.status_code == 400
    assert "aimlapi.com/app/keys" in r.json()["detail"]
    assert oc.read_text() == before


def test_custom_row_named_aimlapi_conflicts_with_preset(client):
    c, _ = client
    rows = [
        {"slot": "aimlapi", "model": "", "baseUrl": BASE, "key": "sk-aiml-fake"},
        {"slot": "custom", "name": "aimlapi", "model": "m", "baseUrl": "https://evil.example.com/v1",
         "key": "sk-other"},
    ]
    r = c.post("/api/settings/models/save", json={"channel": "chat", "rows": rows})
    assert r.status_code == 400
    assert "重名" in r.json()["detail"]


def test_preset_row_only_for_exact_host_and_untouched_users_keep_config(client):
    """没碰预设的用户：保存原有 openai 行不会写出 aimlapi，主模型不变；
    名叫 aimlapi 但根地址不是 api.aimlapi.com 的自定义供应商仍按普通自定义行展示。"""
    c, oc = client
    r = c.post("/api/settings/models/save", json={"channel": "chat", "rows": [
        {"slot": "openai", "model": "deepseek-chat", "baseUrl": "https://api.deepseek.com/v1",
         "key": "sk-deepseek-fake", "primary": True}]})
    assert r.status_code == 200, r.text
    data = json.loads(oc.read_text())
    assert "aimlapi" not in data["models"]["providers"]
    assert data["agents"]["defaults"]["model"]["primary"] == "openai/deepseek-chat"

    data["models"]["providers"]["aimlapi"] = {"baseUrl": "https://other.example.com/v1",
                                              "apiKey": "sk-x", "models": [{"id": "m"}]}
    oc.write_text(json.dumps(data))
    rows = c.get("/api/settings/models").json()["channels"]["chat"]["rows"]
    assert not any(r.get("slot") == "aimlapi" for r in rows)
    assert any(r.get("slot") == "custom" and r["name"] == "aimlapi" for r in rows)

    data["models"]["providers"]["aimlapi"]["baseUrl"] = BASE + "/"
    oc.write_text(json.dumps(data))
    rows = c.get("/api/settings/models").json()["channels"]["chat"]["rows"]
    preset = [r for r in rows if r.get("slot") == "aimlapi"]
    assert len(preset) == 1 and preset[0]["role"] == "备"


# ── 模型列表拉取 ─────────────────────────────────────────────

class _Resp:
    def __init__(self, payload: bytes):
        self._payload, self.status = payload, 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._payload


CATALOG = {"data": [
    {"id": "openai/gpt-4.1-mini", "type": "openai/chat-completions"},
    {"id": "deepseek/deepseek-chat", "type": "openai/chat-completions"},
    {"id": "flux/schnell", "type": "openai/image-generations"},
    {"id": "openai/gpt-4.1-mini", "type": "openai/responses/submit"},
    {"id": "text-embedding-3-small", "type": "openai/embeddings"},
]}


def _stub(monkeypatch, capture):
    monkeypatch.setattr(web, "_ssrf_safe", lambda u: True)

    class _Opener:
        def open(self, rq, timeout=None):
            capture.append((rq.full_url, {k.lower(): v for k, v in rq.header_items()}))
            return _Resp(json.dumps(CATALOG).encode())

    monkeypatch.setattr(web.urllib.request, "build_opener", lambda *a, **k: _Opener())


def test_fetch_uses_public_catalog_and_filters_chat_models(client, monkeypatch):
    c, _ = client
    capture: list = []
    _stub(monkeypatch, capture)
    r = c.post("/api/settings/models/available",
               json={"baseUrl": BASE, "key": "sk-aiml-fake", "slot": "aimlapi"})
    assert r.status_code == 200, r.text
    assert r.json()["models"] == ["deepseek/deepseek-chat", "openai/gpt-4.1-mini"]
    url, headers = capture[0]
    assert url == "https://api.aimlapi.com/v1/models?include=all"
    assert "authorization" not in headers, "公开目录不需要 Key，也就不发 Key"


@pytest.mark.parametrize("bad", ["https://evil.example.com/v1", "https://api.aimlapi.com.evil.example/v1"])
def test_fetch_refuses_other_hosts_for_preset(client, monkeypatch, bad):
    c, oc = client
    data = json.loads(oc.read_text())
    data["models"]["providers"]["aimlapi"] = {"baseUrl": BASE, "apiKey": "sk-aiml-saved",
                                              "models": [{"id": web.AIMLAPI_DEFAULT_MODEL}]}
    oc.write_text(json.dumps(data))
    capture: list = []
    _stub(monkeypatch, capture)
    r = c.post("/api/settings/models/available", json={"baseUrl": bad, "slot": "aimlapi"})
    assert r.status_code == 400
    assert "api.aimlapi.com/v1" in r.json()["detail"]
    assert capture == [], "不该向非 api.aimlapi.com 的地址发出任何请求"


def test_fetch_does_not_follow_redirects(client, monkeypatch):
    """真实 opener：api.aimlapi.com 若返回 302 指向别处，不跟随，也就不会带着任何头去新主机。"""
    c, _ = client
    monkeypatch.setattr(web, "_ssrf_safe", lambda u: True)
    sent: list[str] = []

    class _Redirecting(urllib.request.BaseHandler):
        handler_order = 100

        def https_open(self, req):
            sent.append(req.full_url)
            if "aimlapi.com" not in req.host:
                raise AssertionError(f"跟随了跳转：{req.full_url}")
            import email.message
            import io
            hdrs = email.message.Message()
            hdrs["Location"] = "https://evil.example.com/steal"
            resp = urllib.response.addinfourl(io.BytesIO(b""), hdrs, req.full_url, 302)
            resp.msg = "Found"
            return resp

    real_build = urllib.request.build_opener
    monkeypatch.setattr(web.urllib.request, "build_opener",
                        lambda *a, **k: real_build(*a, _Redirecting, **k))
    r = c.post("/api/settings/models/available",
               json={"baseUrl": BASE, "key": "sk-aiml-fake", "slot": "aimlapi"})
    assert r.status_code == 502
    assert sent == ["https://api.aimlapi.com/v1/models?include=all"]
