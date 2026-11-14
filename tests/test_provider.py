"""v0.2 P6: the model provider is one setting; an OpenAI-compatible endpoint is translated to and from the shape the Session speaks."""
import sys, pathlib, json
import pytest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
from types import SimpleNamespace as NS
from anaplan_architect import provider, codex
from anaplan_architect.openai_compat import ChatClient, to_chat, from_chat

KEYS = ("ANTHROPIC_API_KEY", "ARCHITECT_PROVIDER", "ARCHITECT_MODEL", "OPENAI_BASE_URL", "OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_KEY",
        "AZURE_OPENAI_DEPLOYMENT", "AZURE_OPENAI_API_VERSION", "AWS_REGION", "AWS_DEFAULT_REGION", "CODEX_MODEL", "ANTHROPIC_BASE_URL")


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for k in KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(codex, "available", lambda: False)


def test_one_setting_picks_the_provider(monkeypatch):
    assert provider.resolve()["provider"] == "none" and ".env.example" in provider.resolve()["reason"]
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    r = provider.resolve()
    assert (r["provider"], r["model"], r["endpoint"], provider.client_kw(r)) == ("anthropic", "claude-sonnet-5", "api.anthropic.com", {"api_key": "k"})
    # an OpenAI-compatible endpoint inside an organisation: no key needed, the host is what Settings shows
    monkeypatch.setenv("ARCHITECT_PROVIDER", "openai"); monkeypatch.setenv("OPENAI_BASE_URL", "http://llm.internal:8000/v1")
    assert "ARCHITECT_MODEL" in provider.resolve()["reason"]
    monkeypatch.setenv("ARCHITECT_MODEL", "qwen-coder")
    r = provider.resolve()
    assert (r["provider"], r["model"], r["endpoint"]) == ("openai", "qwen-coder", "llm.internal:8000")
    c = provider.client_kw(r)["client"]
    assert isinstance(c, ChatClient) and c.model == "qwen-coder" and provider.client_kw(r)["client"] is not c       # a client of its own per session
    monkeypatch.setenv("ARCHITECT_PROVIDER", "azure")
    assert "AZURE_OPENAI_ENDPOINT" in provider.resolve()["reason"]
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://corp.openai.azure.com/"); monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "gpt-prod"); monkeypatch.setenv("AZURE_OPENAI_API_KEY", "z")
    r = provider.resolve()
    assert (r["provider"], r["model"], r["endpoint"]) == ("azure", "gpt-prod", "corp.openai.azure.com")
    monkeypatch.setenv("ARCHITECT_PROVIDER", "bedrock"); monkeypatch.setenv("AWS_REGION", "eu-west-2"); monkeypatch.setenv("ARCHITECT_MODEL", "anthropic.claude-sonnet-5-v1:0")
    r = provider.resolve()
    assert (r["provider"], r["model"], r["endpoint"]) == ("bedrock", "anthropic.claude-sonnet-5-v1:0", "bedrock-runtime.eu-west-2.amazonaws.com") and "client_factory" in r["client_kw"]
    monkeypatch.setenv("ARCHITECT_PROVIDER", "nonsense")
    assert provider.resolve()["provider"] == "none" and "must be one of" in provider.resolve()["reason"]
    # auto: an OpenAI-compatible endpoint is picked up when there is no Anthropic key
    monkeypatch.delenv("ANTHROPIC_API_KEY"); monkeypatch.setenv("ARCHITECT_PROVIDER", "auto"); monkeypatch.setenv("ARCHITECT_MODEL", "local-model")
    assert provider.resolve()["provider"] == "openai"


class _Inner:
    """Stands in for openai.OpenAI: records the request, answers with a tool call first, then text."""
    def __init__(self): self.chat = self; self.completions = self; self.seen = []

    def create(self, **kw):
        self.seen.append(kw)
        usage = NS(prompt_tokens=120, completion_tokens=30, prompt_tokens_details=NS(cached_tokens=100))
        if kw["messages"][-1]["role"] == "tool":
            return NS(choices=[NS(message=NS(content="`CAL04 Margin.Margin %` divides.", tool_calls=None))], usage=usage)
        return NS(choices=[NS(message=NS(content=None, tool_calls=[NS(id="call_1", function=NS(name="get_object", arguments='{"name": "CAL04 Margin.Margin %"}'))]))], usage=usage)


def test_chat_completions_round_trip_and_a_whole_turn(tmp_path, monkeypatch):
    msgs, tools = to_chat([{"type": "text", "text": "rules"}, {"type": "text", "text": "estate", "cache_control": {"type": "ephemeral"}}],
                          [{"name": "get_object", "description": "d", "input_schema": {"type": "object", "properties": {"name": {"type": "string"}}}}],
                          [{"role": "user", "content": [{"type": "text", "text": "what is it?", "cache_control": {"type": "ephemeral"}}]},
                           {"role": "assistant", "content": [NS(type="text", text="looking"), NS(type="tool_use", id="c1", name="get_object", input={"name": "X"})]},
                           {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "c1", "content": "{\"ok\": 1}"}]}])
    assert msgs[0] == {"role": "system", "content": "rules\n\nestate"} and msgs[1] == {"role": "user", "content": "what is it?"}
    assert msgs[2]["tool_calls"][0] == {"id": "c1", "type": "function", "function": {"name": "get_object", "arguments": '{"name": "X"}'}} and msgs[2]["content"] == "looking"
    assert msgs[3] == {"role": "tool", "tool_call_id": "c1", "content": '{"ok": 1}'} and tools[0]["function"]["name"] == "get_object"
    out = from_chat({"choices": [{"message": {"content": "hi", "tool_calls": [{"id": "a", "function": {"name": "find", "arguments": "{bad"}}]}}], "usage": {"prompt_tokens": 10, "completion_tokens": 2}}, "m")
    assert [b.type for b in out.content] == ["text", "tool_use"] and out.content[1].input == {"_raw": "{bad"} and out.stop_reason == "tool_use" and out.usage.input_tokens == 10
    # a whole turn through the app, the endpoint standing in for the model
    from fastapi.testclient import TestClient
    from anaplan_architect.web import create_app
    from anaplan_architect import envfile
    monkeypatch.setattr(envfile, "candidates", lambda: [])
    inner = _Inner()
    app = create_app(tmp_path / "data", client_factory=lambda: ChatClient("local-model", inner=inner))
    c = TestClient(app)
    li = (pathlib.Path(__file__).parent / "fixtures" / "estate" / "1 Caldergate Planning" / "Line Items.csv").read_bytes()
    eid = c.post("/api/estates", data={"name": "P", "model_names": ["Caldergate Planning"]}, files=[("line_items", ("Line Items.csv", li, "text/csv"))]).json()["id"]
    t = c.post(f"/api/estates/{eid}/conversations", json={"title": "q", "text": "what is margin %?"}).json()["turns"][0]
    assert t["verification"]["clean"] and t["tools"][0]["tool"] == "get_object" and t["usage"]["cache_read"] == 200 and t["usage"]["input"] == 40
    first = inner.seen[0]
    assert first["model"] == "claude-sonnet-5" and first["messages"][0]["role"] == "system" and first["tool_choice"] == "auto" and first["max_completion_tokens"] == 8000
    assert any(tl["function"]["name"] == "build_plan" and tl["function"]["parameters"]["properties"]["modules"]["type"] == "array" for tl in first["tools"])


def test_a_failed_codex_token_refresh_does_not_repeat_what_the_token_service_said(tmp_path, monkeypatch):
    """Not covered by either review of 2026-11-13 (codex.py). A failed refresh put the token service's reply into the
    error, and a model error is shown to whoever asked the question. The error names the status, not the reply."""
    import httpx
    p = tmp_path / "auth.json"
    p.write_text(json.dumps({"tokens": {"access_token": "", "refresh_token": "rt-abc"}}), encoding="utf-8")
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: NS(status_code=401, text='{"error":"invalid_grant","account":"someone@example.org","detail":"refresh token rt-abc revoked"}', json=lambda: {}))
    with pytest.raises(codex.CodexAuthError) as e:
        codex.CodexAuth(p).access_token()
    said = str(e.value)
    assert "401" in said and "codex login" in said and "someone@example.org" not in said and "rt-abc" not in said and "invalid_grant" not in said
