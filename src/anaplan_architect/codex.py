"""Run the architect on a ChatGPT subscription through the Codex backend,
with no API key: a local route (`LLM_PROVIDER=codex`).

`codex login` (the official CLI) writes OAuth tokens to ~/.codex/auth.json.
This module reads them, refreshes the access token when it is about to
expire, and speaks the Responses API at chatgpt.com/backend-api/codex. It
presents the subset of the Anthropic client that `chat.Session` uses:

    client.messages.stream(model=, system=[...], tools=[...], messages=[...])
        -> context manager, iterable of events shaped like the Anthropic SDK's
           (content_block_start / content_block_delta), get_final_message()

so the conversation loop, transcripts, statuses and memories are untouched.
The backend is undocumented and reverse-engineered; these are the quirks
(stream only, no max tokens, no sampling
parameters, non-empty instructions, strict schemas for structured output).
"""
from __future__ import annotations
import base64, binascii, hashlib, json, os, threading, time, datetime
from pathlib import Path
from types import SimpleNamespace

CODEX_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
CODEX_TOKEN_URL = "https://auth.openai.com/oauth/token"
CODEX_BASE_URL = "https://chatgpt.com/backend-api/codex"
DEFAULT_MODEL = "gpt-5.5"


def configured_model() -> str | None:
    """The model the Codex CLI itself is set to use (the top-level `model = "..."` of config.toml beside auth.json). A
    subscription stops serving older models, so the route follows what `codex` runs rather than a name fixed here."""
    import re
    try:
        text = (auth_path().parent / "config.toml").read_text(encoding="utf-8")
    except OSError:
        return None
    head = text.split(chr(10) + "[", 1)[0]               # before the first table: the top-level keys
    m = re.search(r'(?m)^\s*model\s*=\s*"([^"]+)"', head)
    return m.group(1) if m else None
_SKEW = 60


class CodexAuthError(RuntimeError):
    pass


def auth_path() -> Path:
    home = os.environ.get("CODEX_HOME") or os.path.join(os.path.expanduser("~"), ".codex")
    return Path(home) / "auth.json"


def available() -> bool:
    return auth_path().is_file()


def _claims(token: str) -> dict:
    if not token or token.count(".") < 2:
        return {}
    p = token.split(".")[1]; p += "=" * (-len(p) % 4)
    try:
        c = json.loads(base64.urlsafe_b64decode(p.encode("ascii")))
        return c if isinstance(c, dict) else {}
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return {}


class CodexAuth:
    """Reads and refreshes the tokens `codex login` wrote. One lock per process."""
    def __init__(self, path: Path | None = None):
        self.path = path or auth_path(); self._lock = threading.Lock()

    def _read(self) -> dict:
        if not self.path.exists():
            raise CodexAuthError(f"no Codex credentials at {self.path}: install the Codex CLI (npm i -g @openai/codex) and run `codex login`")
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            raise CodexAuthError(f"cannot read {self.path}: {e}; re-run `codex login`") from e
        return d if isinstance(d, dict) else {}

    def account_id(self) -> str | None:
        t = self._read().get("tokens") or {}
        if t.get("account_id"):
            return t["account_id"]
        a = _claims(t.get("id_token") or "").get("https://api.openai.com/auth") or {}
        return a.get("chatgpt_account_id") if isinstance(a, dict) else None

    def access_token(self, force_refresh: bool = False) -> str:
        with self._lock:
            d = self._read(); t = d.get("tokens") or {}
            access, refresh = t.get("access_token"), t.get("refresh_token")
            if access and not force_refresh:
                exp = _claims(access).get("exp")
                if not isinstance(exp, (int, float)) or exp - time.time() > _SKEW:
                    return access
            if not refresh:
                if access:
                    return access
                raise CodexAuthError(f"no refresh_token in {self.path}; run `codex login`")
            import httpx
            r = httpx.post(CODEX_TOKEN_URL, json={"client_id": CODEX_CLIENT_ID, "grant_type": "refresh_token", "refresh_token": refresh,
                                                  "scope": "openid profile email"}, timeout=30.0)
            if r.status_code != 200:
                # the status only: the reply can name the account or the token, and a model error is shown to whoever asked
                raise CodexAuthError(f"Codex token refresh failed ({r.status_code}); run `codex login` on the server")
            b = r.json()
            for k in ("access_token", "refresh_token", "id_token"):
                if b.get(k):
                    t[k] = b[k]
            d["tokens"] = t; d["last_refresh"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            tmp = self.path.with_suffix(".json.tmp"); tmp.write_text(json.dumps(d, indent=2), encoding="utf-8"); os.replace(tmp, self.path)
            return t["access_token"]


# ---------- Anthropic-shaped blocks the Session reads back ----------

class TextBlock(SimpleNamespace):
    type = "text"


class ToolUseBlock(SimpleNamespace):
    type = "tool_use"


def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(b.get("text", "") if isinstance(b, dict) else getattr(b, "text", "") for b in content if (b.get("type") if isinstance(b, dict) else getattr(b, "type", "")) == "text")
    return str(content or "")


def to_responses(system, tools, messages) -> tuple[str, list[dict], list[dict]]:
    """Anthropic-shaped request -> (instructions, tools, input) for the Responses API."""
    instructions = "\n\n".join(_text_of([b]) if isinstance(b, dict) else str(b) for b in (system if isinstance(system, list) else [system])) or "You are a helpful assistant."
    rtools = [{"type": "function", "name": t["name"], "description": t.get("description", ""), "parameters": t.get("input_schema") or {"type": "object", "properties": {}}} for t in tools or []]
    items: list[dict] = []
    for m in messages:
        role, content = m["role"], m["content"]
        if role == "user":
            if isinstance(content, list) and content and isinstance(content[0], dict) and content[0].get("type") == "tool_result":
                for b in content:
                    out = b.get("content", "")
                    items.append({"type": "function_call_output", "call_id": b["tool_use_id"], "output": out if isinstance(out, str) else json.dumps(out)})
            else:
                items.append({"type": "message", "role": "user", "content": [{"type": "input_text", "text": _text_of(content)}]})
        elif role == "assistant":
            blocks = content if isinstance(content, list) else [TextBlock(text=str(content))]
            text = "".join(getattr(b, "text", "") for b in blocks if getattr(b, "type", "") == "text")
            if text:
                items.append({"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": text}]})
            for b in blocks:
                if getattr(b, "type", "") == "tool_use":
                    items.append({"type": "function_call", "call_id": b.id, "name": b.name, "arguments": json.dumps(b.input or {})})
    return instructions, rtools, items


class _Stream:
    """Iterates Responses events, yields Anthropic-shaped events, builds the final message."""
    def __init__(self, raw, model: str):
        self.raw = raw; self.model = model
        self.blocks: list = []; self._args: dict[int, dict] = {}; self._text = ""; self.usage = None

    def __enter__(self): return self

    def __exit__(self, *a):
        close = getattr(self.raw, "close", None)
        if close:
            try: close()
            except Exception: pass
        return False

    def __iter__(self):
        for ev in self.raw:
            et = getattr(ev, "type", "") or (ev.get("type") if isinstance(ev, dict) else "")
            g = (lambda k, d=None: ev.get(k, d)) if isinstance(ev, dict) else (lambda k, d=None: getattr(ev, k, d))
            if et == "response.output_text.delta":
                d = g("delta", "") or ""
                if d:
                    self._text += d
                    yield SimpleNamespace(type="content_block_delta", delta=SimpleNamespace(type="text_delta", text=d))
            elif et == "response.output_item.added":
                item = g("item"); ig = (lambda k, d=None: item.get(k, d)) if isinstance(item, dict) else (lambda k, d=None: getattr(item, k, d))
                if ig("type") == "function_call":
                    idx = g("output_index", len(self._args))
                    self._args[idx] = {"id": ig("call_id") or ig("id"), "name": ig("name"), "args": ig("arguments") or ""}
                    yield SimpleNamespace(type="content_block_start", content_block=SimpleNamespace(type="tool_use", name=ig("name")))
            elif et == "response.function_call_arguments.delta":
                idx = g("output_index"); d = g("delta", "") or ""
                self._args.setdefault(idx, {"id": None, "name": None, "args": ""})["args"] += d
            elif et == "response.output_item.done":
                item = g("item"); ig = (lambda k, d=None: item.get(k, d)) if isinstance(item, dict) else (lambda k, d=None: getattr(item, k, d))
                if ig("type") == "function_call":
                    idx = g("output_index"); slot = self._args.setdefault(idx, {"id": None, "name": None, "args": ""})
                    slot["id"] = ig("call_id") or ig("id") or slot["id"]; slot["name"] = ig("name") or slot["name"]
                    if ig("arguments"):
                        slot["args"] = ig("arguments")
            elif et == "response.completed":
                resp = g("response"); u = (resp.get("usage") if isinstance(resp, dict) else getattr(resp, "usage", None)) if resp else None
                ug = (lambda k, d=0: u.get(k, d)) if isinstance(u, dict) else (lambda k, d=0: getattr(u, k, d) if u else d)
                det = ug("input_tokens_details", None)
                cached = (det.get("cached_tokens") if isinstance(det, dict) else getattr(det, "cached_tokens", 0)) if det else 0
                inp = ug("input_tokens", 0) or 0
                self.usage = SimpleNamespace(input_tokens=max(inp - (cached or 0), 0), output_tokens=ug("output_tokens", 0) or 0,
                                             cache_read_input_tokens=cached or 0, cache_creation_input_tokens=0)
                return
            elif et in ("response.failed", "response.incomplete", "error"):
                resp = g("response"); err = g("message") or (resp.get("error", {}).get("message") if isinstance(resp, dict) else None)
                raise RuntimeError(f"Codex responses stream {et}: {err or 'unknown error'}")

    def get_final_message(self):
        content: list = []
        if self._text:
            content.append(TextBlock(text=self._text))
        for idx in sorted(self._args):
            s = self._args[idx]
            try:
                args = json.loads(s["args"] or "{}")
            except json.JSONDecodeError:
                args = {"_raw": s["args"]}
            content.append(ToolUseBlock(id=s["id"] or f"call_{idx}", name=s["name"], input=args))
        return SimpleNamespace(content=content, usage=self.usage, model=self.model,
                               stop_reason="tool_use" if self._args else "end_turn")


class CodexClient:
    """`client.messages.stream(...)` over the Codex backend. `inner_factory(token)`
    may be injected (tests); by default it builds an OpenAI SDK client."""
    def __init__(self, model: str = DEFAULT_MODEL, reasoning_effort: str | None = "medium", base_url: str = CODEX_BASE_URL,
                 auth: CodexAuth | None = None, inner_factory=None):
        self.model = model; self.effort = reasoning_effort; self.base_url = base_url
        self.auth = auth or CodexAuth(); self.inner_factory = inner_factory
        self.messages = self

    def _inner(self, token: str):
        if self.inner_factory:
            return self.inner_factory(token)
        from openai import OpenAI
        return OpenAI(base_url=self.base_url, api_key=token)

    def _headers(self) -> dict:
        h = {"OpenAI-Beta": "responses=experimental", "originator": "codex_cli_rs"}
        acc = self.auth.account_id()
        if acc:
            h["ChatGPT-Account-ID"] = acc
        return h

    def stream(self, model=None, system=None, tools=None, messages=(), **_ignored) -> _Stream:
        instructions, rtools, items = to_responses(system, tools, list(messages))
        rk = {"model": model if (model or "").startswith("gpt") else self.model, "instructions": instructions, "input": items, "store": False,
              "prompt_cache_key": hashlib.sha1((instructions + json.dumps(rtools, sort_keys=True)).encode("utf-8")).hexdigest()[:32]}
        if rtools:
            rk["tools"] = rtools; rk["tool_choice"] = "auto"
        if self.effort:
            rk["reasoning"] = {"effort": self.effort}
        last = None
        for attempt in (0, 1):
            token = self.auth.access_token(force_refresh=attempt > 0)
            try:
                raw = self._inner(token).responses.create(**rk, stream=True, extra_headers=self._headers())
                return _Stream(raw, rk["model"])
            except Exception as e:
                last = e
                if attempt == 0 and getattr(e, "status_code", None) == 401:
                    continue
                raise
        raise last
