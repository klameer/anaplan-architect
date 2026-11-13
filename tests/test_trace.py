"""Tracing (the demo story, 2026-09-28; LangSmith since 2026-11-13): the full trace of a conversation as a hierarchy.
A fake tracer records what the session hands it; a fake LangSmith client records what the real tracer sends. The shape
must be one root run per conversation, one run per question under it, and under the turn, in order, an llm run per
model call, a tool run per tool call, the validator with its verdict, and the scores on the turn."""
import sys, pathlib, contextlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
from fastapi.testclient import TestClient
from anaplan_architect.web import create_app
from fakes import FAKE_PT, FAKE_SK, FAKE_TR, FAKE_ANT
from anaplan_architect.orac import telemetry
from test_web import _Fake, _upload

ENV = ("LANGSMITH_API_KEY", "LANGCHAIN_API_KEY", "LANGSMITH_ENDPOINT", "LANGSMITH_PROJECT")


class _U:
    def __init__(self, o): self.o = o

    def update(self, **kw): self.o.update(kw)


class FakeTurn:
    enabled = True

    def __init__(self, name, kw):
        self.name, self.kw, self.children, self.out, self.score = name, kw, [], None, {}

    @contextlib.contextmanager
    def generation(self, name, model, input=None):
        o = {"kind": "generation", "name": name, "model": model, "input": input}; self.children.append(o); yield _U(o)

    @contextlib.contextmanager
    def tool(self, name, args=None):
        o = {"kind": "tool", "name": name, "args": args}; self.children.append(o); yield _U(o)

    def validator(self, verdict, names=None): self.children.append({"kind": "guardrail", "verdict": verdict, "names": names})

    def scores(self, values): self.score.update(values)

    def output(self, text): self.out = text


class FakeTracer:
    enabled = True
    host = "fake"
    error = None

    def __init__(self): self.turns = []

    def status(self): return {"enabled": True, "host": "fake", "error": None}

    @contextlib.contextmanager
    def turn(self, name, **kw):
        t = FakeTurn(name, kw); self.turns.append(t); yield t


def test_a_conversation_traces_as_a_hierarchy(tmp_path):
    fake = FakeTracer()
    app = create_app(tmp_path / "data", client_factory=_Fake, tracer=fake)
    c = TestClient(app)
    eid = _upload(c).json()["id"]
    assert c.get("/api/auth/me").json()["tracing"] == {"enabled": True, "host": "fake", "error": None}
    cid = c.post(f"/api/estates/{eid}/conversations", json={"title": "traced"}).json()["id"]
    r = c.post(f"/api/conversations/{cid}/messages", json={"text": "what divides?"})
    assert r.status_code == 200
    assert len(fake.turns) == 1
    t = fake.turns[0]
    assert t.name == "what divides?" and t.kw["session_id"] == cid and t.kw["input"] == "what divides?"
    assert t.kw["metadata"]["estate"] == eid and t.kw["metadata"]["snapshot"] and t.kw["metadata"]["conversation"] == cid
    conv = t.kw["conversation"]
    assert conv["id"] == cid and conv["title"] == "traced" and conv["state"] is None and callable(conv["save"])
    kept = {"trace_id": "t" * 32, "root_run_id": "t" * 32, "root_dotted_order": "d", "host": "fake", "project": "p"}
    conv["save"](kept)          # what the real tracer does on the first turn
    # the hierarchy, in the order things happened: model call, the tool it asked for, the model call that answered, the check
    assert [x["kind"] for x in t.children] == ["generation", "tool", "generation", "guardrail"]
    g1, tool, g2, guard = t.children
    assert g1["model"] == app.state.model_id and g1["usage"] == {"input": 100, "output": 20, "cache_read": 0, "cache_write": 9000} and "cost_usd" in g1
    assert g1["output"] == [{"tool_use": "list_models", "input": {}}]
    assert tool["name"] == "list_models" and tool["args"] == {} and tool["output"]["chars"] > 0 and tool["output"]["cites"] >= 2 and "models" in tool["output"]["preview"]
    assert g2["usage"]["cache_read"] == 9000 and g2["output"][0]["text"].startswith("Turn 1")
    # the fake names a real line item it never looked up (unchecked) and one the estate does not contain (unverified)
    assert guard["verdict"]["cited"] == 0 and guard["verdict"]["unchecked"] == 1 and guard["verdict"]["unverified"] == 1 and guard["names"]["unverified"] == ["Ghost.Nope"]
    assert t.score["cited"] == 0 and t.score["unchecked"] == 1 and t.score["unverified"] == 1 and t.score["clean"] is False and t.score["tool_calls"] == 1 and t.score["model_calls"] == 2
    assert t.score["cost_usd"] >= 0 and t.out.startswith("Turn 1")
    # the second question is a second turn of the same conversation, and finds the state the first one saved
    c.post(f"/api/conversations/{cid}/messages", json={"text": "and again?"})
    assert len(fake.turns) == 2 and fake.turns[1].kw["session_id"] == cid and fake.turns[1].name == "and again?"
    assert fake.turns[1].kw["conversation"]["state"] == kept   # kept in the store


class FakeLangSmith:
    """The SDK's Client as far as the tracer uses it: it records create_run and update_run, and never leaves the process."""

    def __init__(self, **kw): self.kw, self.calls, self.flushed, self.checked = kw, [], 0, 0

    def create_run(self, name, inputs, run_type, **kw):
        self.calls.append(("create", {"name": name, "inputs": inputs, "run_type": run_type, **kw}))

    def update_run(self, run_id, **kw): self.calls.append(("update", {"id": run_id, **kw}))

    def list_projects(self, limit=None): self.checked += 1; return iter(())

    def flush(self): self.flushed += 1

    @property
    def created(self): return [kw for op, kw in self.calls if op == "create"]

    def updates(self, run_id): return [kw for op, kw in self.calls if op == "update" and kw["id"] == run_id]

    def children(self, run_id): return [r for r in self.created if r.get("parent_run_id") == run_id]


def test_tracing_is_off_without_a_key_and_nothing_is_sent(monkeypatch):
    for k in ENV:
        monkeypatch.delenv(k, raising=False)
    made = []
    t = telemetry.Tracer.from_env(factory=lambda **kw: made.append(kw))
    assert made == []                                    # no key: no client is even built
    assert not t.enabled and t.status() == {"enabled": False, "host": None, "error": None, "backend": "langsmith", "ceiling": "content", "write_only": False}
    with t.turn("q", session_id="c1") as turn:
        assert isinstance(turn, telemetry.NullTurn)
        with turn.generation("model", "m") as g:
            g.update(output="x", usage={"input": 1})
        with turn.tool("find", {"text": "x"}) as tl:
            tl.update(output={"chars": 1})
        turn.validator({"cited": 0}); turn.scores({"cited": 0}); turn.output("done")
    assert not hasattr(t, "ls") or getattr(t, "ls", None) is None      # and no client was made (the SDK itself may be loaded: it ships a pytest plugin)


def test_the_key_turns_it_on_and_names_the_project_and_endpoint(monkeypatch):
    for k in ENV:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("LANGCHAIN_API_KEY", FAKE_PT)   # the older name is read too
    t = telemetry.Tracer.from_env(factory=FakeLangSmith)
    assert t.enabled and t.client.kw == {"api_url": "https://api.smith.langchain.com", "api_key": FAKE_PT}
    assert t.client.checked == 1 and t.project == "anaplan-architect"
    assert t.status() == {"enabled": True, "host": "https://api.smith.langchain.com", "error": None, "backend": "langsmith", "ceiling": "content", "write_only": False}
    monkeypatch.setenv("LANGSMITH_API_KEY", FAKE_SK)
    monkeypatch.setenv("LANGSMITH_ENDPOINT", "https://eu.api.smith.langchain.com/")
    monkeypatch.setenv("LANGSMITH_PROJECT", "caldergate")
    t = telemetry.Tracer.from_env(factory=FakeLangSmith)
    assert t.client.kw["api_key"].startswith("lsv2_sk_") and t.host == "https://eu.api.smith.langchain.com" and t.project == "caldergate"

    # a client that cannot be built, or a key the endpoint refuses: off, and Settings can say why
    def refuse(**kw): raise RuntimeError("no such package")
    t = telemetry.Tracer.from_env(factory=refuse)
    assert not t.enabled and "no such package" in t.status()["error"] and t.status()["host"] == "https://eu.api.smith.langchain.com"

    class Rejected(FakeLangSmith):
        def list_projects(self, limit=None): raise PermissionError("401")
    t = telemetry.Tracer.from_env(factory=Rejected)
    assert not t.enabled and "did not accept the key" in t.error


def test_the_mask_strips_secrets():
    assert telemetry.mask({"k": FAKE_ANT, "ls": "key " + FAKE_PT + " here",
                           "who": "karim@example.com", "n": 3, "l": ["ok"]}) == \
        {"k": "[REDACTED_KEY]", "ls": "key [REDACTED_KEY] here", "who": "[REDACTED_EMAIL]", "n": 3, "l": ["ok"]}


def test_one_trace_per_conversation_with_turns_under_its_root():
    ls = FakeLangSmith()
    tracer = telemetry.Tracer(client=ls, host="stub", project="proj")
    kept = {}
    conv = lambda: {"id": "c-1", "title": "The estate", "state": kept.get("s"), "save": lambda st: kept.__setitem__("s", st), "metadata": {"estate": "e1"}}
    secret = "ask karim@example.com, key " + FAKE_ANT
    with tracer.turn("first question", session_id="c-1", user_id="karim", metadata={"turn": 1}, tags=["demo"], input=secret, conversation=conv()) as t:
        with t.generation("model", "m", input={"messages": [{"role": "user", "content": secret}]}) as g:
            g.update(output=[{"text": "hi karim@example.com"}], usage={"input": 1, "output": 2, "cache_read": 30, "cache_write": 400}, cost_usd=0.001)
        with t.tool("find", {"text": secret}) as tl:
            tl.update(output={"chars": 3, "cites": 2, "preview": secret})
        t.validator({"cited": 1, "clean": True}, {"unverified": []}); t.scores({"cited": 1, "clean": True, "skipped": None}); t.output("hi")
    root, turn1, llm, tool, verify = ls.created
    # the conversation is the root run, named by its title, and its place is what the next turn is handed
    assert root["name"] == "The estate" and root["run_type"] == "chain" and "parent_run_id" not in root and root["trace_id"] == root["id"]
    assert root["project_name"] == "proj" and root["extra"]["metadata"] == {"estate": "e1", "thread_id": "c-1", "session_id": "c-1", "user_id": "karim"}
    assert kept["s"] == {"trace_id": str(root["id"]), "root_run_id": str(root["id"]), "root_dotted_order": root["dotted_order"], "host": "stub", "project": "proj"}
    # the turn hangs off the root; the model call, the tool and the validator hang off the turn, in the order they happened
    assert turn1["name"] == "first question" and turn1["run_type"] == "chain" and turn1["parent_run_id"] == root["id"] and turn1["tags"] == ["demo"]
    assert [(r["name"], r["run_type"]) for r in ls.children(turn1["id"])] == [("model", "llm"), ("find", "tool"), ("verify", "chain")]
    assert ls.children(root["id"]) == [turn1] and all(r["trace_id"] == root["id"] and r["project_name"] == "proj" for r in ls.created)
    assert turn1["dotted_order"].startswith(root["dotted_order"] + ".") and turn1["dotted_order"].endswith(str(turn1["id"]))
    kids = [llm, tool, verify]
    assert all(k["dotted_order"].startswith(turn1["dotted_order"] + ".") and k["dotted_order"].endswith(str(k["id"])) for k in kids)
    assert [k["dotted_order"] for k in kids] == sorted(k["dotted_order"] for k in kids)             # LangSmith reads them in this order
    assert root["start_time"] < turn1["start_time"] < llm["start_time"] < tool["start_time"] < verify["start_time"]
    # the model call: what came back, tokens as LangSmith counts them (cached inside the input), cost in metadata
    (lu,) = ls.updates(llm["id"])
    assert lu["parent_run_id"] == turn1["id"] and lu["trace_id"] == root["id"] and lu["dotted_order"] == llm["dotted_order"] and lu["end_time"] > llm["start_time"]
    assert lu["outputs"]["usage_metadata"] == {"input_tokens": 431, "output_tokens": 2, "total_tokens": 433, "input_token_details": {"cache_read": 30, "cache_creation": 400}}
    assert lu["extra"]["metadata"]["cost_usd"] == 0.001 and lu["extra"]["metadata"]["ls_model_name"] == "m" and lu["extra"]["metadata"]["usage"]["cache_write"] == 400
    # the tool call: arguments in, size, citations and a preview out
    (tu,) = ls.updates(tool["id"])
    assert tool["inputs"] == {"text": "ask [REDACTED_EMAIL], key [REDACTED_KEY]"} and tu["outputs"]["chars"] == 3 and tu["outputs"]["cites"] == 2
    # the validator is complete when it is written: the verdict is its output
    assert verify["outputs"] == {"cited": 1, "clean": True} and verify["inputs"] == {"unverified": []} and verify["end_time"] and ls.updates(verify["id"]) == []
    # the turn closes with the answer and the scores as metadata, in the one update: no feedback call, no extra request
    (uu,) = ls.updates(turn1["id"])
    assert uu["outputs"] == {"output": "hi"} and uu["parent_run_id"] == root["id"] and "error" not in uu
    assert uu["extra"]["metadata"] == {"turn": 1, "thread_id": "c-1", "session_id": "c-1", "user_id": "karim", "score_cited": 1, "score_clean": True}
    assert ls.updates(root["id"])[-1]["outputs"] == {"last_question": "first question", "output": "hi"} and "extra" not in ls.updates(root["id"])[-1]
    assert {op for op, _ in ls.calls} == {"create", "update"} and ls.flushed == 1
    # secrets are masked in everything that was handed to the client
    sent = repr(ls.calls)
    assert "karim@example.com" not in sent and "sk-ant-" not in sent and "[REDACTED_EMAIL]" in sent and "[REDACTED_KEY]" in sent
    assert turn1["inputs"] == {"input": "ask [REDACTED_EMAIL], key [REDACTED_KEY]"} and lu["outputs"]["output"] == [{"text": "hi [REDACTED_EMAIL]"}]

    # the second turn attaches under the same root, and no new root is made
    with tracer.turn("second question", session_id="c-1", user_id="karim", input="second question", conversation=conv()) as t:
        t.output("again")
    assert len(ls.created) == 6 and [r for r in ls.created if "parent_run_id" not in r] == [root]
    turn2 = ls.created[5]
    assert turn2["parent_run_id"] == root["id"] and turn2["trace_id"] == root["id"] and turn2["dotted_order"].startswith(root["dotted_order"] + ".")
    assert kept["s"]["root_run_id"] == str(root["id"]) and ls.flushed == 2 and tracer.error is None
    # a turn that fails is closed with its error, and the error still reaches the caller
    try:
        with tracer.turn("third", session_id="c-1", input="third", conversation=conv()) as t:
            with t.tool("find", {}):
                raise ValueError("boom")
    except ValueError:
        pass
    turn3 = ls.created[6]
    assert turn3["parent_run_id"] == root["id"] and ls.updates(turn3["id"])[0]["error"] == "ValueError: boom" and ls.updates(ls.created[7]["id"])[0]["error"] == "ValueError: boom"
    # a state saved against another host is not trusted: a fresh root is made here
    kept["s"] = kept["s"] | {"host": "elsewhere"}
    with tracer.turn("fourth", session_id="c-1", input="fourth", conversation=conv()) as t:
        pass
    assert kept["s"]["host"] == "stub" and kept["s"]["root_run_id"] != str(root["id"]) and len([r for r in ls.created if "parent_run_id" not in r]) == 2


def test_a_client_that_fails_never_breaks_the_answer():
    class Broken(FakeLangSmith):
        def create_run(self, *a, **kw): raise ConnectionError("down")
    tracer = telemetry.Tracer(client=Broken(), host="stub")
    with tracer.turn("q", session_id="c-1", input="q", conversation={"id": "c-1", "title": "t"}) as t:
        assert isinstance(t, telemetry.NullTurn)
        t.output("fine")
    assert tracer.status()["error"] == "ConnectionError: down" and tracer.enabled


def test_the_session_traces_to_langsmith_and_the_store_keeps_the_root(tmp_path):
    """The real tracer behind the app: two questions in one conversation are two turns under one root, because the
    store (conversations.trace_json) hands the first turn's state to the second."""
    ls = FakeLangSmith()
    app = create_app(tmp_path / "data", client_factory=_Fake, tracer=telemetry.Tracer(client=ls, host="stub"))
    c = TestClient(app)
    eid = _upload(c).json()["id"]
    assert c.get("/api/auth/me").json()["tracing"] == {"enabled": True, "host": "stub", "error": None, "backend": "langsmith", "ceiling": "content", "write_only": False}
    cid = c.post(f"/api/estates/{eid}/conversations", json={"title": "traced"}).json()["id"]
    assert c.post(f"/api/conversations/{cid}/messages", json={"text": "what divides?"}).status_code == 200
    assert c.post(f"/api/conversations/{cid}/messages", json={"text": "and again?"}).status_code == 200
    roots = [r for r in ls.created if "parent_run_id" not in r]
    assert len(roots) == 1 and roots[0]["name"] == "traced" and roots[0]["extra"]["metadata"]["thread_id"] == cid
    turn1, turn2 = ls.children(roots[0]["id"])
    assert turn1["name"] == "what divides?" and turn2["name"] == "and again?" and turn1["extra"]["metadata"]["estate"] == eid
    kids = ls.children(turn1["id"])
    assert [(k["name"], k["run_type"]) for k in kids] == [("model", "llm"), ("list_models", "tool"), ("model", "llm"), ("verify", "chain")]
    assert "material" not in kids[0]["inputs"] and kids[0]["inputs"]["material_chars"] > 0          # the estate material is not sent
    assert ls.updates(kids[0]["id"])[0]["outputs"]["usage_metadata"]["input_token_details"] == {"cache_read": 0, "cache_creation": 9000}
    assert ls.updates(kids[1]["id"])[0]["outputs"]["cites"] >= 2 and kids[3]["outputs"]["unverified"] == 1
    meta = ls.updates(turn1["id"])[0]["extra"]["metadata"]
    assert meta["score_unverified"] == 1 and meta["score_clean"] is False and meta["score_tool_calls"] == 1 and meta["score_model_calls"] == 2
    assert ls.updates(turn1["id"])[0]["outputs"]["output"].startswith("Turn 1") and app.state.tracer.error is None


def test_content_is_off_by_default_and_a_trace_then_carries_structure_only(monkeypatch):
    """What a trace holds with content off and with it on (which of the two a turn gets is decided per login:
    tests/test_trace_levels.py). Off: the hierarchy, the tool names and their order, sizes, tokens, cost, timings and
    the verdict's counts; no question, answer, tool argument or result, document text, object name or title. On: the
    content too. The same turn is recorded both ways and compared."""
    off = telemetry.Tracer(FakeLangSmith(), host="stub", content=False)
    on = telemetry.Tracer(FakeLangSmith(), host="stub", content=True)

    SECRETS = ["Why is the account mapping", "CAL03 Opex", "Forecast Opex", "Finance Systems did not want planners", "Caldergate FP&A", "Opex review chat",
               "the mapping was a control", "SYS05 FX Rates", "ZeroDivisionError: CAL04", "design decision record"]

    def record(tracer):
        meta = {"estate": "e-1", "snapshot": "sn-1", "conversation": "c-9", "model": "claude-sonnet-5-5", "scope": {"model": "Caldergate FP&A", "module": "CAL03 Opex"}, "turn": 2}
        conv = {"id": "c-9", "title": "Opex review chat", "state": None, "save": lambda st: None, "metadata": {"estate": "e-1", "conversation": "c-9", "model": "claude-sonnet-5-5"}}
        with tracer.turn("Why is the account mapping in Forecast Opex?", session_id="c-9", user_id="u-1", metadata=meta, tags=["Caldergate FP&A"],
                         input="Why is the account mapping in Forecast Opex?", conversation=conv) as t:
            with t.generation("model", "claude-sonnet-5-5", input={"system": "You are the architect of Caldergate FP&A", "messages": [{"role": "user", "content": "Why is the account mapping"}]}) as g:
                g.update(output=[{"type": "tool_use", "name": "get_section", "input": {"section": "s-1"}}], usage={"input": 900, "output": 40, "cache_read": 100, "cache_write": 0}, cost_usd=0.004)
            with t.tool("search_documents", {"query": "account mapping Forecast Opex", "objects": ["CAL03 Opex.Forecast Opex"]}) as tl:
                tl.update(output={"chars": 812, "cites": 3, "preview": "design decision record 4.3: Finance Systems did not want planners to edit"})
            try:
                with t.tool("get_object", {"name": "SYS05 FX Rates"}):
                    raise ZeroDivisionError("CAL04 Margin.Margin % divides by zero")
            except ZeroDivisionError:
                pass
            t.validator({"cited": 4, "unchecked": 0, "unverified": 1, "phantom": ["s-zzz"], "clean": False, "quotes": {"checked": 2, "found": 2, "missing": []},
                         "figures": {"checked": 3, "untraced": ["12%"]}}, {"unverified": ["CAL03 Opex.Forecast Opex"], "unchecked": [], "phantom": ["s-zzz"], "untraced": ["12%"]})
            t.scores({"cited": 4, "unverified": 1, "clean": False, "cost_usd": 0.004, "tool_calls": 2, "model_calls": 1})
            t.output("the mapping was a control: Finance Systems did not want planners to edit it")
        return tracer.client

    a, b = record(off), record(on)
    sent = repr(a.calls)
    assert not [w for w in SECRETS if w in sent], [w for w in SECRETS if w in sent]              # nothing a user wrote or a workspace holds
    assert all(w in repr(b.calls) for w in SECRETS)                                               # with content on, it is all there
    # the structure is the same either way: the same runs, of the same types, in the same order, with the same parents
    kinds = lambda ls: [(r["run_type"], "parent_run_id" in r) for r in ls.created]
    assert kinds(a) == kinds(b) and len(a.created) == 6 and len(a.calls) == len(b.calls)
    root, turn, llm, search, getobj, verify = a.created
    assert (root["name"], turn["name"]) == ("conversation", "turn 2") and b.created[0]["name"] == "Opex review chat"
    assert [r["name"] for r in a.created[2:]] == ["model", "search_documents", "get_object", "verify"]          # tool names and their order stay
    assert "tags" not in turn and b.created[1]["tags"] == ["Caldergate FP&A"]
    # sizes in place of content
    assert turn["inputs"] == {"input": {"chars": 44}} and search["inputs"] == {"query": {"chars": 29}, "objects": {"items": 1}} and llm["inputs"] == {"system": {"chars": 40}, "messages": {"items": 1}}
    (su,) = a.updates(search["id"])
    assert su["outputs"] == {"chars": 812, "cites": 3, "preview": {"chars": 73}} and su["end_time"] > search["start_time"]
    # tokens, cost and the model's name stay; ids stay; the scope's object names do not
    (lu,) = a.updates(llm["id"])
    assert lu["outputs"]["usage_metadata"]["input_tokens"] == 1000 and lu["outputs"]["output"] == {"items": 1}
    assert lu["extra"]["metadata"] == {"ls_model_name": "claude-sonnet-5-5", "ls_model_type": "chat", "model": "claude-sonnet-5-5", "usage": {"input": 900, "output": 40, "cache_read": 100, "cache_write": 0}, "cost_usd": 0.004}
    (tu,) = a.updates(turn["id"])
    m = tu["extra"]["metadata"]
    assert m["estate"] == "e-1" and m["user_id"] == "u-1" and m["turn"] == 2 and m["scope"] == {"model": {"chars": 15}, "module": {"chars": 10}}
    assert (m["score_cited"], m["score_unverified"], m["score_clean"], m["score_cost_usd"], m["score_tool_calls"]) == (4, 1, False, 0.004, 2)
    assert tu["outputs"] == {"output": {"chars": 75}}
    # the verdict: its counts, never the names it flagged
    assert verify["outputs"] == {"cited": 4, "unchecked": 0, "unverified": 1, "phantom": {"items": 1}, "clean": False, "quotes": {"checked": 2, "found": 2, "missing": {"items": 0}},
                                 "figures": {"checked": 3, "untraced": {"items": 1}}}
    assert verify["inputs"] == {"unverified": {"items": 1}, "unchecked": {"items": 0}, "phantom": {"items": 1}, "untraced": {"items": 1}}
    # an error keeps its type and loses its text
    assert a.updates(getobj["id"])[0]["error"] == "ZeroDivisionError" and "divides by zero" in b.updates(b.created[4]["id"])[0]["error"]
    # a dict keyed by something that is not a plain field name does not carry the key out
    assert telemetry.shape({"by_model": {"Caldergate FP&A": 24, "ok_key": 1}}) == {"key_0": {"key_0": 24, "key_1": 1}}          # nor one that merely looks like a field name


def test_the_notice_says_what_the_operator_sees_and_that_tracing_is_each_logins_own_choice(tmp_path):
    """Before anyone uploads, the sign-in notice says the operator sees usage figures and, when tracing is set up, that
    a login's questions are not sent anywhere unless that login turns it on."""
    said = {}
    for label, tracer in (("off", telemetry.Tracer(None)), ("on", telemetry.Tracer(FakeLangSmith(), host="stub"))):
        app = create_app(tmp_path / label, client_factory=lambda: None, tracer=tracer)
        said[label] = TestClient(app).get("/api/auth/me").json()
    assert all("can see usage figures for each login" in v["notice"] for v in said.values())
    assert "Tracing" not in said["off"]["notice"] and said["off"]["trace"]["available"] is False
    n = said["on"]["notice"]
    assert "Tracing to LangSmith is set up here" in n and "unless you turn that on for yourself in Settings" in n and "The admin's own questions are traced" in n
    assert said["on"]["tracing"]["ceiling"] == "content" and said["on"]["trace"]["available"] is True


def test_a_structure_only_trace_keeps_only_field_names_it_knows():
    """Security review 2026-11-13, S10. With content off, a dict key that looked like a plain field name was kept, so
    an object named in lower case (a module called opex, a list called regions) used as a key would have left."""
    out = telemetry.shape({"query": "account mapping", "opex": 12, "regions": {"north": 1}, "cites": 3, "score_clean": True, "by_model": {"fpa": 2}})
    assert out == {"query": {"chars": 15}, "key_1": 12, "key_2": {"key_0": 1}, "cites": 3, "score_clean": True, "key_5": {"key_0": 2}}
    # every tool's own parameter names are known, so the shape of a call still reads
    args = telemetry.shape({"model": "FP&A", "function": "FINDITEM", "group_by": "module", "limit": 25, "modules": [{"name": "x"}], "checks_after": ["a"]})
    assert args == {"model": {"chars": 4}, "function": {"chars": 8}, "group_by": {"chars": 6}, "limit": 25, "modules": {"items": 1}, "checks_after": {"items": 1}}
