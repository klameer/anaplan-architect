"""Any OpenAI-compatible chat-completions endpoint as the model behind the architect (v0.2 P6): OpenAI itself, Azure
OpenAI, or a server that speaks the same protocol inside an organisation (vLLM, Ollama, LiteLLM, a gateway).

The Session speaks Anthropic's Messages shape (system blocks, tool definitions, tool_use and tool_result blocks). This
adapter translates a request to chat completions and the reply back, so nothing else in the app knows which provider
answered. `client.messages.create(...)` only: the Session falls back to it when a client has no `stream`.
"""
from __future__ import annotations
import json
from types import SimpleNamespace


class TextBlock(SimpleNamespace):
    type = "text"


class ToolUseBlock(SimpleNamespace):
    type = "tool_use"


def _text(content) -> str:
    if isinstance(content, str):
        return content
    out = []
    for b in content or []:
        t = b.get("type") if isinstance(b, dict) else getattr(b, "type", "")
        if t == "text":
            out.append(b.get("text", "") if isinstance(b, dict) else getattr(b, "text", ""))
    return "".join(out)


def to_chat(system, tools, messages) -> tuple[list[dict], list[dict]]:
    """Anthropic-shaped request -> (messages, tools) for chat completions."""
    sys_text = "\n\n".join(_text([b]) if isinstance(b, dict) else str(b) for b in (system if isinstance(system, list) else [system] if system else []))
    out: list[dict] = [{"role": "system", "content": sys_text}] if sys_text else []
    for m in messages:
        role, content = m["role"], m["content"]
        if role == "user":
            if isinstance(content, list) and content and isinstance(content[0], dict) and content[0].get("type") == "tool_result":
                for b in content:
                    c = b.get("content", "")
                    out.append({"role": "tool", "tool_call_id": b["tool_use_id"], "content": c if isinstance(c, str) else json.dumps(c)})
            else:
                out.append({"role": "user", "content": _text(content)})
        elif role == "assistant":
            blocks = content if isinstance(content, list) else [TextBlock(text=str(content))]
            get = lambda b, k: b.get(k) if isinstance(b, dict) else getattr(b, k, None)
            msg: dict = {"role": "assistant", "content": "".join(get(b, "text") or "" for b in blocks if get(b, "type") == "text") or None}
            calls = [{"id": get(b, "id"), "type": "function", "function": {"name": get(b, "name"), "arguments": json.dumps(get(b, "input") or {})}} for b in blocks if get(b, "type") == "tool_use"]
            if calls:
                msg["tool_calls"] = calls
            out.append(msg)
    ctools = [{"type": "function", "function": {"name": t["name"], "description": t.get("description", ""), "parameters": t.get("input_schema") or {"type": "object", "properties": {}}}} for t in tools or []]
    return out, ctools


def from_chat(resp, model: str):
    """A chat completion -> an Anthropic-shaped message (content blocks, usage, stop_reason)."""
    g = (lambda o, k, d=None: o.get(k, d) if isinstance(o, dict) else getattr(o, k, d))
    choice = (g(resp, "choices") or [None])[0]
    msg = g(choice, "message") if choice is not None else None
    content: list = []
    text = g(msg, "content") if msg is not None else None
    if text:
        content.append(TextBlock(text=text))
    for i, c in enumerate(g(msg, "tool_calls") or [] if msg is not None else []):
        fn = g(c, "function")
        raw = g(fn, "arguments") or "{}"
        try:
            args = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except json.JSONDecodeError:
            args = {"_raw": raw}
        content.append(ToolUseBlock(id=g(c, "id") or f"call_{i}", name=g(fn, "name"), input=args))
    u = g(resp, "usage")
    det = g(u, "prompt_tokens_details") if u is not None else None
    cached = (g(det, "cached_tokens", 0) or 0) if det is not None else 0
    prompt = (g(u, "prompt_tokens", 0) or 0) if u is not None else 0
    usage = SimpleNamespace(input_tokens=max(prompt - cached, 0), output_tokens=(g(u, "completion_tokens", 0) or 0) if u is not None else 0,
                            cache_read_input_tokens=cached, cache_creation_input_tokens=0)
    return SimpleNamespace(content=content, usage=usage, model=model, stop_reason="tool_use" if any(b.type == "tool_use" for b in content) else "end_turn")


class ChatClient:
    """`client.messages.create(...)` over a chat-completions endpoint. `inner` is an `openai.OpenAI` or
    `openai.AzureOpenAI` client (or anything with `.chat.completions.create`); injectable for tests."""
    def __init__(self, model: str, inner=None, base_url: str | None = None, api_key: str | None = None, azure: dict | None = None, max_tokens_param: str = "max_completion_tokens"):
        self.model = model; self.messages = self; self.max_tokens_param = max_tokens_param
        if inner is None:
            import openai
            if azure:
                inner = openai.AzureOpenAI(azure_endpoint=azure["endpoint"], api_key=azure.get("api_key"), api_version=azure.get("api_version") or "2024-10-21")
            else:
                inner = openai.OpenAI(base_url=base_url or None, api_key=api_key or "not-needed")
        self.inner = inner

    def create(self, model=None, system=None, tools=None, messages=(), max_tokens: int | None = None, **_ignored):
        msgs, ctools = to_chat(system, tools, list(messages))
        kw = {"model": model or self.model, "messages": msgs}
        if ctools:
            kw["tools"] = ctools; kw["tool_choice"] = "auto"
        if max_tokens:
            kw[self.max_tokens_param] = max_tokens
        try:
            resp = self.inner.chat.completions.create(**kw)
        except TypeError:
            raise
        except Exception as e:
            if self.max_tokens_param in kw and self.max_tokens_param in str(e):      # an older server knows only max_tokens
                kw["max_tokens"] = kw.pop(self.max_tokens_param); self.max_tokens_param = "max_tokens"
                resp = self.inner.chat.completions.create(**kw)
            else:
                raise
        return from_chat(resp, kw["model"])
