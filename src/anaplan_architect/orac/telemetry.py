"""Tracing: the full trace of a conversation as a hierarchy, in LangSmith (the demo story, 2026-09-28; LangSmith
since 2026-11-13, the v0.2 plan, "Tracing").

One LangSmith trace per conversation: a root run (run_type "chain") named by the conversation's title, created on its
first turn and remembered through the conversation's trace state (trace id, root run id, the root's dotted order, host,
project), so every later turn, on any server start, attaches under the same root. Under the root, one chain run per
turn (named by the question), and under each turn, in the order things happened: an "llm" run for every model call
(model, what it was given, what came back, tokens with cache reads and writes, cost in metadata), a "tool" run for
every tool the architect called (arguments, result size, citations minted, a preview of the result), and a run named
`verify` for the validator carrying the verdict. The verdict's numbers are also written as metadata on the turn's run
(`score_cited`, `score_unchecked`, `score_unverified`, `score_phantom`, `score_untraced_figures`, `score_clean`,
`score_cost_usd`, `score_tool_calls`, `score_model_calls`): they travel with the update that closes the turn, so they
cost no extra request, and they can be filtered on in LangSmith. Metadata names the estate, the snapshot, the model and
the scope; the conversation is the thread and the account asking is the user.

Off unless LANGSMITH_API_KEY (or LANGCHAIN_API_KEY) is set; the project is LANGSMITH_PROJECT (default
"anaplan-architect"); the endpoint is LANGSMITH_ENDPOINT, defaulting to https://api.smith.langchain.com. The estate
material is never sent unless LANGSMITH_TRACE_MATERIAL=1 (chat.py): what reaches the trace store is the question, the
answer, tool arguments and results, and the numbers. A mask strips key-shaped strings and email addresses from every
payload before it is handed to the client. Tracing never raises: a failure is kept on the tracer as `error` (Settings
shows it) and the answer goes on.

What a turn sends is decided per turn, by the level of whoever asked (the web app passes it; see `turn`): off, nothing
at all; structure, each run's place in the hierarchy, its type, the tool's name, its timings, tokens, cost and the
verdict's counts, with every string that could carry what was asked or what the workspace holds (the question, the
answer, tool arguments and results, document text, object names, the conversation's title, error text) replaced by
its size before the client sees it (`shape`); content, all of it. LANGSMITH_TRACE_CONTENT=0 is a ceiling for the whole
instance: nobody's turn goes above structure. On a hosted instance the operator reads the trace store, and so does
LangSmith, which is why a login that is not the admin's sends nothing until that login turns it on for itself.

Every run is written with the SDK's `Client.create_run` / `Client.update_run` and an explicit parent, trace id and
dotted order, never with `@traceable` or the SDK's context variables: the session streams its answer through a
generator that resumes on different threads, so a 'current run' set at one yield is gone at the next, and anything
that relied on it landed as a root of its own. Giving the trace id and dotted order also lets the SDK queue the runs
and send them in batches from its own thread. `langsmith` is imported only when a key is set.
"""
from __future__ import annotations
import contextlib
import datetime
import logging
import os
import re
import threading
import uuid

log = logging.getLogger(__name__)
BACKEND = "langsmith"
DEFAULT_HOST = "https://api.smith.langchain.com"
DEFAULT_PROJECT = "anaplan-architect"

_MASK = [
    (re.compile(r"\b(?:sk|pk|rk)-(?:[A-Za-z]{2,10}-)?[A-Za-z0-9_-]{16,}\b"), "[REDACTED_KEY]"),
    (re.compile(r"\b(?:lsv2_[a-z]{2}_|ls__)[A-Za-z0-9_]{16,}\b"), "[REDACTED_KEY]"),          # personal, service and tracing-only keys
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "[REDACTED_EMAIL]"),
]


def mask(data):
    """Key-shaped strings and email addresses never reach the trace store; everything else passes as it is."""
    if isinstance(data, str):
        for rx, rep in _MASK:
            data = rx.sub(rep, data)
        return data
    if isinstance(data, dict):
        return {k: mask(v) for k, v in data.items()}
    if isinstance(data, (list, tuple)):
        return [mask(v) for v in data]
    return data


_KEY = re.compile(r"^[a-z_][a-z0-9_]{0,40}$")
# metadata whose value is an id, a model name or a fixed word, never something a user wrote or a workspace holds
SAFE_META = {"thread_id", "session_id", "user_id", "estate", "snapshot", "conversation", "model", "ls_model_name", "ls_model_type", "kind"}


# Field names a trace may carry with content off: the tracer's own, the verdict's, usage, and (added on first use) the
# parameter names of the chat tools. Anything else used as a key could be an object's name, whatever it looks like,
# and is numbered instead.
_FIELDS = {"input", "output", "conversation", "system", "messages", "tools", "chars", "cites", "preview", "items", "usage", "usage_metadata", "input_tokens",
           "output_tokens", "total_tokens", "input_token_details", "cache_read", "cache_creation", "cache_write", "cost_usd", "turn", "scope", "estate", "snapshot",
           "model", "module", "thread_id", "session_id", "user_id", "ls_model_name", "ls_model_type", "kind", "mode", "last_question", "cited", "unchecked", "unverified",
           "phantom", "clean", "quotes", "checked", "found", "missing", "figures", "traced", "derived", "untraced", "benign", "why", "sources", "not_recorded",
           "unsupported", "role", "content", "type", "name", "id", "text", "error"}
_tool_fields: set | None = None


def _known(key: str) -> bool:
    global _tool_fields
    if key in _FIELDS or key.startswith("score_"):
        return True
    if _tool_fields is None:
        found: set = set()
        try:
            from ..tools import Toolbox

            def walk(node):
                if isinstance(node, dict):
                    for k, v in (node.get("properties") or {}).items():
                        found.add(k); walk(v)
                    walk(node.get("items"))
                elif isinstance(node, list):
                    for x in node:
                        walk(x)
            for t in Toolbox.schema():
                walk(t.get("input_schema"))
        except Exception as e:                      # without the tool list only the fixed names are kept: less is said, never more
            log.warning("tracing: tool parameter names not read: %s", e)
        _tool_fields = found
    return key in _tool_fields


def shape(data, safe: frozenset | set = frozenset()):
    """The structure of a payload with its content taken out: numbers and booleans stay, a string becomes its length,
    a list its count, a dict keeps a key only when it is a field name this code knows (the tracer's, the verdict's, a
    tool's parameter); any other key is numbered, because it could be an object's name. A string under a key in `safe`
    stays: an id or a fixed word."""
    if data is None or isinstance(data, (bool, int, float)):
        return data
    if isinstance(data, str):
        return {"chars": len(data)}
    if isinstance(data, dict):
        out = {}
        for i, (k, v) in enumerate(data.items()):
            k = str(k)
            # a safe key counts at the top level only: `model` there is the LLM's name, inside `scope` it is a model of the estate
            out[k if _known(k) else f"key_{i}"] = (v if isinstance(v, str) and k in safe else shape(v))
        return out
    if isinstance(data, (list, tuple, set)):
        return {"items": len(data)}
    return {"chars": len(str(data))}


class NullTurn:
    """The hierarchy when tracing is off: every method is a context manager or a no-op, so callers never branch."""
    enabled = False

    @contextlib.contextmanager
    def generation(self, name: str, model: str, input=None):
        yield self

    @contextlib.contextmanager
    def tool(self, name: str, args=None):
        yield self

    def update(self, **kw) -> None:
        pass

    def validator(self, verdict: dict | None, names: dict | None = None) -> None:
        pass

    def scores(self, values: dict) -> None:
        pass

    def output(self, text: str) -> None:
        pass


class Tracer:
    """`turn(...)` is the one entry point. Built with a LangSmith client (anything with `create_run` and `update_run`:
    the SDK's `Client`, or a fake in tests) it records the hierarchy; built without one it hands out NullTurns. Errors
    while recording are kept on `error`, never raised."""

    def __init__(self, client=None, host: str | None = None, error: str | None = None, project: str | None = None, content: bool = True,
                 ceiling: str = "content", write_only: bool = False):
        self.client, self.host, self.error = client, host, error
        self.content = content          # what a turn sends when it names no level: True, everything; False, structure only
        self.ceiling = ceiling          # "structure": no turn of this instance sends content, whatever its level
        self.write_only = write_only    # a tracing-only key: runs can be written, nothing can be read back through it
        self.project = project or DEFAULT_PROJECT
        self._last = None
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self.client is not None

    @classmethod
    def from_env(cls, factory=None) -> "Tracer":
        """factory(api_url=, api_key=) builds the client; by default the SDK's `Client`, imported here and only when a
        key is set, so the package runs without `langsmith` installed."""
        env = lambda k: os.environ.get(k, "").strip()
        key = env("LANGSMITH_API_KEY") or env("LANGCHAIN_API_KEY")
        ceiling = "structure" if env("LANGSMITH_TRACE_CONTENT").lower() in ("0", "false", "no") else "content"
        if not key:
            return cls(None, None, None, ceiling=ceiling)
        host = (env("LANGSMITH_ENDPOINT") or DEFAULT_HOST).rstrip("/")
        project = env("LANGSMITH_PROJECT") or DEFAULT_PROJECT
        try:
            if factory is None:
                from langsmith import Client as factory
            client = factory(api_url=host, api_key=key)
        except Exception as e:                       # a missing package or a bad endpoint: the app runs, Settings says why tracing is off
            log.warning("tracing off: %s", e)
            return cls(None, host, f"{type(e).__name__}: {e} (pip install -e .[trace])"[:300], project, ceiling=ceiling)
        try:                                          # one round trip at startup, so a wrong endpoint or key shows on Settings at once
            check = getattr(client, "list_projects", None)
            if check is not None:
                next(iter(check(limit=1)), None)
        except Exception as e:
            # A tracing-only key may write runs and read nothing: listing projects is refused with 403 and those words.
            # That is a key that works. Anything else (401, a wrong region, no network) is a key that does not.
            if "403" in str(e) and "tracing keys" in str(e):
                return cls(client, host, None, project, ceiling=ceiling, write_only=True)
            log.warning("tracing off: %s", e)
            return cls(None, host, f"{host} did not accept the key: {type(e).__name__}: {e}"[:300], project, ceiling=ceiling)
        return cls(client, host, None, project, ceiling=ceiling)

    def status(self) -> dict:
        return {"enabled": self.enabled, "host": self.host, "error": self.error, "backend": BACKEND, "ceiling": self.ceiling, "write_only": bool(self.write_only)}

    # what leaves for the trace store: everything (masked) with content on, the structure alone with it off
    def inputs(self, data, content: bool | None = None):
        return mask(data) if (self.content if content is None else content) else shape(data)

    def meta(self, data, content: bool | None = None):
        return mask(data) if (self.content if content is None else content) else shape(data, SAFE_META)

    def errtext(self, text: str, content: bool | None = None) -> str:
        return mask(text) if (self.content if content is None else content) else str(text).split(":", 1)[0][:80]

    def _fail(self, e: BaseException) -> None:
        self.error = f"{type(e).__name__}: {e}"[:300]
        log.warning("tracing: %s", e)

    def _now(self) -> datetime.datetime:
        """UTC, and strictly later than the last one handed out: LangSmith orders siblings by start time, and two runs
        made within one clock tick must still read in the order they happened."""
        with self._lock:
            t = datetime.datetime.now(datetime.timezone.utc)
            if self._last is not None and t <= self._last:
                t = self._last + datetime.timedelta(microseconds=1)
            self._last = t
            return t

    @contextlib.contextmanager
    def turn(self, name: str, *, session_id: str | None = None, user_id: str | None = None, metadata: dict | None = None,
             tags: list[str] | None = None, input=None, conversation: dict | None = None, level: str | None = None, fixed_name: bool = False):
        """conversation: {id, title, state, save, metadata}. `state` is what an earlier turn saved ({trace_id,
        root_run_id, root_dotted_order, host, project}) or None; `save(state)` is called when the root is created, so
        the next turn finds it.
        `level` is what this turn may send: "off" (nothing), "structure" or "content"; None keeps the tracer's own
        default. The instance's ceiling applies on top. `fixed_name` says the name is one this code chose (not a
        question or a title), so it may stay when content is off."""
        if not self.enabled or level == "off":
            yield NullTurn()
            return
        content = self.content if level is None else (level == "content")
        if self.ceiling == "structure":
            content = False
        t = LangSmithTurn(self, name, session_id, user_id, metadata, tags, input, conversation, content=content, fixed_name=fixed_name)
        try:
            t.open()
        except Exception as e:
            self._fail(e)
            yield NullTurn()
            return
        try:
            yield t
        except BaseException as e:
            t.close(error=f"{type(e).__name__}: {e}"[:300])
            raise
        else:
            t.close()


def _dotted(start: datetime.datetime, run_id, parent: str | None = None) -> str:
    """LangSmith's dotted order: one `<start time><run id>` segment per ancestor, root first."""
    seg = start.strftime("%Y%m%dT%H%M%S%f") + "Z" + str(run_id)
    return f"{parent}.{seg}" if parent else seg


def _as_dict(value, key: str) -> dict | None:
    """Run inputs and outputs are objects in LangSmith; anything else is wrapped under one key."""
    if value is None:
        return None
    return value if isinstance(value, dict) else {key: value}


class _Run:
    """One run in the trace: where it sits (id, parent, dotted order) and what the caller says came back. `update`
    only collects; the run is closed with one `update_run` when its block ends."""

    def __init__(self, run_id, dotted: str, parent_id=None, metadata: dict | None = None):
        self.id, self.dotted, self.parent_id = run_id, dotted, parent_id
        self.metadata = dict(metadata or {})
        self.outputs: dict | None = None

    def update(self, **kw) -> None:
        if "output" in kw:
            self.outputs = (self.outputs or {}) | (_as_dict(kw["output"], "output") or {})
        if kw.get("metadata"):
            self.metadata.update(kw["metadata"])
        u = kw.get("usage")
        if u:
            cached, written = u.get("cache_read", 0) or 0, u.get("cache_write", 0) or 0
            given = (u.get("input", 0) or 0) + cached + written          # LangSmith counts cached tokens inside the input
            self.outputs = (self.outputs or {}) | {"usage_metadata": {
                "input_tokens": given, "output_tokens": u.get("output", 0) or 0, "total_tokens": given + (u.get("output", 0) or 0),
                "input_token_details": {"cache_read": cached, "cache_creation": written}}}
            self.metadata["usage"] = dict(u)
        if kw.get("cost_usd") is not None:
            self.metadata["cost_usd"] = kw["cost_usd"]


class LangSmithTurn:
    """One turn of the conversation: a chain run under the conversation's root, the conversation as its thread, the
    account as its user. Every child is created with its parent's id, the trace id and a dotted order built here,
    never from a 'current run' (see the module docstring: the streaming generator changes threads)."""
    enabled = True

    def __init__(self, tracer: Tracer, name: str, session_id, user_id, metadata, tags, input, conversation: dict | None = None,
                 content: bool | None = None, fixed_name: bool = False):
        self.tracer, self.ls = tracer, tracer.client
        self.content = tracer.content if content is None else content          # this turn's own: decided by who asked
        self.name, self.session_id, self.user_id, self.metadata, self.tags, self.input = name, session_id, user_id, metadata, tags, input
        self.conversation = conversation or {}
        if not self.content:            # the question names the turn and the title names the conversation: neither leaves
            if not fixed_name:
                self.name = f"turn {(metadata or {}).get('turn', '')}".strip()
            self.conversation = {**self.conversation, "title": "conversation"}
            self.tags = None
        self._root: _Run | None = None
        self._run: _Run | None = None
        self._out = None
        self.trace_id: str | None = None

    def _who(self) -> dict:
        """The conversation as LangSmith's thread, the account as its user."""
        cid = self.conversation.get("id") or self.session_id
        return {k: v for k, v in (("thread_id", cid), ("session_id", self.session_id), ("user_id", self.user_id)) if v}

    def _create(self, name: str, run_type: str, inputs, parent: _Run | None, metadata: dict | None = None,
                outputs=None, done: bool = False) -> _Run:
        start = self.tracer._now()
        rid = uuid.uuid4()
        run = _Run(rid, _dotted(start, rid, parent.dotted if parent else None), parent.id if parent else None, metadata)
        kw = {"id": rid, "trace_id": self._root.id if self._root else rid, "dotted_order": run.dotted, "start_time": start,
              "project_name": self.tracer.project, "extra": {"metadata": self.tracer.meta(run.metadata, self.content)}}
        if parent is not None:
            kw["parent_run_id"] = parent.id
        if self.tags:
            kw["tags"] = list(self.tags)
        if outputs is not None:
            kw["outputs"] = self.tracer.inputs(_as_dict(outputs, "output"), self.content)
        if done:
            kw["end_time"] = self.tracer._now()
        self.ls.create_run(name=(name or run_type)[:120], inputs=self.tracer.inputs(_as_dict(inputs, "input") or {}, self.content), run_type=run_type, **kw)
        return run

    def _finish(self, run: _Run | None, error: str | None = None, metadata: bool = True) -> None:
        if run is None:
            return
        try:
            kw = {"end_time": self.tracer._now(), "trace_id": self._root.id, "dotted_order": run.dotted}
            if run.parent_id is not None:
                kw["parent_run_id"] = run.parent_id
            if run.outputs is not None:
                kw["outputs"] = self.tracer.inputs(run.outputs, self.content)
            if error:
                kw["error"] = self.tracer.errtext(error, self.content)
            if metadata:                              # sent whole: an update replaces the run's metadata, it does not add to it
                kw["extra"] = {"metadata": self.tracer.meta(run.metadata, self.content)}
            self.ls.update_run(run.id, **kw)
        except Exception as e:
            self.tracer._fail(e)

    def open(self) -> None:
        conv = self.conversation
        state = dict(conv.get("state") or {})
        root = None
        if state.get("root_run_id") and state.get("root_dotted_order") and state.get("host") == self.tracer.host \
                and state.get("project", self.tracer.project) == self.tracer.project:
            try:
                root = _Run(uuid.UUID(str(state["root_run_id"])), str(state["root_dotted_order"]))
            except ValueError:
                root = None
        if root is None:
            # the conversation's first turn on this store: one trace, with the conversation as its root run
            title = (conv.get("title") or self.name or "conversation")[:120]
            root = self._create(title, "chain", {"conversation": title}, None, (conv.get("metadata") or self.metadata or {}) | self._who())
            state = {"trace_id": str(root.id), "root_run_id": str(root.id), "root_dotted_order": root.dotted,
                     "host": self.tracer.host, "project": self.tracer.project}
            save = conv.get("save")
            if save is not None:
                try:
                    save(state)
                except Exception as e:
                    self.tracer._fail(e)
        self._root = root
        self.trace_id = str(root.id)
        self._run = self._create(self.name, "chain", self.input, root, (self.metadata or {}) | self._who())

    def close(self, error: str | None = None) -> None:
        if self._run is None:
            return
        if self._out is not None:
            self._run.outputs = (self._run.outputs or {}) | {"output": self._out}
        self._finish(self._run, error)
        # the root ends where its latest turn ended and shows that turn's answer; its metadata is left as it was made
        self._root.outputs = {"last_question": self.name} | ({"output": self._out} if self._out is not None else {})
        self._finish(self._root, metadata=False)
        flush = getattr(self.ls, "flush", None)       # a one-shot CLI question exits right after its answer
        if flush is not None:
            try:
                flush()
            except Exception as e:
                self.tracer._fail(e)

    def _child(self, name: str, run_type: str, inputs, metadata: dict | None = None, outputs=None, done: bool = False) -> _Run | None:
        try:
            return self._create(name, run_type, inputs, self._run, metadata, outputs, done)
        except Exception as e:
            self.tracer._fail(e)
            return None

    @contextlib.contextmanager
    def _under(self, run: _Run | None):
        if run is None:
            yield NullTurn()
            return
        try:
            yield run
        except BaseException as e:
            self._finish(run, error=f"{type(e).__name__}: {e}"[:300])
            raise
        else:
            self._finish(run)

    @contextlib.contextmanager
    def generation(self, name: str, model: str, input=None):
        meta = {"ls_model_name": model, "ls_model_type": "chat", "model": model}
        with self._under(self._child(name, "llm", input, meta)) as o:
            yield o

    @contextlib.contextmanager
    def tool(self, name: str, args=None):
        with self._under(self._child(name, "tool", args if args is not None else {})) as o:
            yield o

    def validator(self, verdict: dict | None, names: dict | None = None) -> None:
        self._child("verify", "chain", names or {}, {"kind": "guardrail"}, outputs=verdict or {}, done=True)

    def scores(self, values: dict) -> None:
        """The verdict as `score_<name>` metadata on the turn's run, so every turn of the conversation keeps its own.
        Sent with the update that closes the turn: no request of its own."""
        if self._run is None:
            return
        for k, v in values.items():
            if v is not None:
                self._run.metadata[f"score_{k}"] = v

    def output(self, text: str) -> None:
        self._out = text


_default: Tracer | None = None


def default(refresh: bool = False) -> Tracer:
    """The process-wide tracer, built from the environment once (after envfile.load has run)."""
    global _default
    if _default is None or refresh:
        _default = Tracer.from_env()
    return _default
