"""Which model answers, from the environment (.env is loaded first). One setting picks the provider; the rest of the
app never knows which one it is.

  ARCHITECT_PROVIDER = anthropic | bedrock | azure | openai | codex | auto (default)

    anthropic  ANTHROPIC_API_KEY (or --api-key); ARCHITECT_MODEL, default claude-sonnet-5
    bedrock    Claude on Amazon Bedrock: AWS credentials from the usual chain, AWS_REGION; ARCHITECT_MODEL = the Bedrock
               model id (required)
    azure      Azure OpenAI: AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY, AZURE_OPENAI_DEPLOYMENT (or ARCHITECT_MODEL),
               AZURE_OPENAI_API_VERSION (optional)
    openai     any OpenAI-compatible chat-completions endpoint, OpenAI's own or one inside your organisation:
               OPENAI_BASE_URL (omit for api.openai.com), OPENAI_API_KEY (omit if the endpoint needs none),
               ARCHITECT_MODEL (required)
    codex      a ChatGPT subscription through `codex login` (~/.codex/auth.json); CODEX_MODEL, default the model in
               ~/.codex/config.toml; CODEX_REASONING (low|medium|high), default medium
    auto       anthropic when a key is present, else openai when OPENAI_BASE_URL or OPENAI_API_KEY and ARCHITECT_MODEL
               are set, else codex when auth.json exists, else none

`resolve()` returns {"provider", "model", "client_kw", "endpoint"}: client_kw feeds chat.Session ({"api_key": ...} for
Anthropic, {"client": ...} or {"client_factory": ...} otherwise), and endpoint is where the questions go, shown in
Settings so nobody has to guess what leaves the machine.
"""
from __future__ import annotations
import os
from . import codex as codexmod

PROVIDERS = ("anthropic", "bedrock", "azure", "openai", "codex", "auto")


def _host(url: str | None) -> str:
    if not url:
        return ""
    return url.split("://", 1)[-1].split("/", 1)[0]


def _none(reason: str) -> dict:
    return {"provider": "none", "model": None, "client_kw": {}, "endpoint": "", "reason": reason}


def resolve(api_key: str | None = None, model_id: str | None = None) -> dict:
    env = os.environ.get
    key = api_key or env("ANTHROPIC_API_KEY")
    want = (env("ARCHITECT_PROVIDER") or "auto").lower()
    model = model_id or env("ARCHITECT_MODEL")
    if want not in PROVIDERS:
        return _none(f"ARCHITECT_PROVIDER must be one of {', '.join(PROVIDERS)}; got {want!r}")
    if want in ("anthropic", "auto") and key:
        return {"provider": "anthropic", "model": model or "claude-sonnet-5", "client_kw": {"api_key": key}, "endpoint": _host(env("ANTHROPIC_BASE_URL")) or "api.anthropic.com"}
    if want == "bedrock":
        if not model:
            return _none("bedrock: set ARCHITECT_MODEL to the Bedrock model id")
        region = env("AWS_REGION") or env("AWS_DEFAULT_REGION")

        def make():
            import anthropic
            return anthropic.AnthropicBedrock(**({"aws_region": region} if region else {}))
        return {"provider": "bedrock", "model": model, "client_kw": {"client_factory": make}, "endpoint": f"bedrock-runtime.{region or 'your-region'}.amazonaws.com"}
    if want == "azure":
        endpoint, dep = env("AZURE_OPENAI_ENDPOINT"), env("AZURE_OPENAI_DEPLOYMENT") or model
        if not endpoint or not dep:
            return _none("azure: set AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY and AZURE_OPENAI_DEPLOYMENT")

        def make():
            from .openai_compat import ChatClient
            return ChatClient(dep, azure={"endpoint": endpoint, "api_key": env("AZURE_OPENAI_API_KEY"), "api_version": env("AZURE_OPENAI_API_VERSION")})
        return {"provider": "azure", "model": dep, "client_kw": {"client_factory": make}, "endpoint": _host(endpoint)}
    if want == "openai" or (want == "auto" and model and (env("OPENAI_BASE_URL") or env("OPENAI_API_KEY"))):
        if not model:
            return _none("openai: set ARCHITECT_MODEL to the model the endpoint serves")
        base = env("OPENAI_BASE_URL")

        def make():
            from .openai_compat import ChatClient
            return ChatClient(model, base_url=base, api_key=env("OPENAI_API_KEY"))
        return {"provider": "openai", "model": model, "client_kw": {"client_factory": make}, "endpoint": _host(base) or "api.openai.com"}
    if want in ("codex", "auto") and codexmod.available():
        cmodel = env("CODEX_MODEL") or codexmod.configured_model() or codexmod.DEFAULT_MODEL
        effort = env("CODEX_REASONING") or "medium"
        return {"provider": "codex", "model": cmodel, "client_kw": {"client": codexmod.CodexClient(model=cmodel, reasoning_effort=effort)}, "endpoint": "chatgpt.com (Codex subscription)"}
    reason = {"anthropic": "set ANTHROPIC_API_KEY (or --api-key)", "codex": f"run `codex login` (no {codexmod.auth_path()})"}.get(
        want, "set ANTHROPIC_API_KEY; or ARCHITECT_PROVIDER=openai with OPENAI_BASE_URL and ARCHITECT_MODEL; or run `codex login` and set ARCHITECT_PROVIDER=codex")
    return _none(reason)


def client_kw(backend: dict) -> dict:
    """What chat.Session takes for this backend: a fresh client per session where the provider has a factory."""
    kw = backend.get("client_kw") or {}
    if "client_factory" in kw:
        return {"client": kw["client_factory"]()}
    return dict(kw)
