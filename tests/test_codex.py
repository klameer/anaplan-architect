import sys, pathlib, json
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
from types import SimpleNamespace as NS
from anaplan_architect import codex
from anaplan_architect.store import Workspace
from anaplan_architect import chat

FX = pathlib.Path(__file__).parent / "fixtures" / "estate"


class _FakeAuth:
    def __init__(self): self.calls = []
    def account_id(self): return "acct_1"
    def access_token(self, force_refresh=False): self.calls.append(force_refresh); return "tok"


class _Responses:
    """Scripted Responses stream: first request calls get_object, second answers."""
    def __init__(self, box): self.box = box

    def create(self, **kw):
        self.box.append(kw)
        assert kw["stream"] is True and kw["store"] is False and "max_output_tokens" not in kw and "temperature" not in kw
        assert kw["extra_headers"]["ChatGPT-Account-ID"] == "acct_1" and kw["reasoning"] == {"effort": "medium"}
        n = len(self.box)
        if n == 1:
            assert kw["input"][-1]["type"] == "message" and kw["tools"][0]["name"] == "list_models"
            return iter([
                NS(type="response.output_item.added", output_index=0, item=NS(type="function_call", call_id="c1", name="get_object", arguments="")),
                NS(type="response.function_call_arguments.delta", output_index=0, delta='{"name": "CAL04 Margin.Margin %"}'),
                NS(type="response.output_item.done", output_index=0, item=NS(type="function_call", call_id="c1", name="get_object", arguments='{"name": "CAL04 Margin.Margin %"}')),
                NS(type="response.completed", response=NS(usage=NS(input_tokens=1000, output_tokens=20, input_tokens_details=NS(cached_tokens=800)))),
            ])
        # second call: the history must carry the function_call and its output
        kinds = [i["type"] for i in kw["input"]]
        assert kinds[-2:] == ["function_call", "function_call_output"] and "Net Revenue" in kw["input"][-1]["output"]
        return iter([
            NS(type="response.output_text.delta", delta="`CAL04 Margin.Margin %` divides "),
            NS(type="response.output_text.delta", delta="by `CAL04 Margin.Net Revenue`."),
            NS(type="response.completed", response=NS(usage=NS(input_tokens=1200, output_tokens=15, input_tokens_details=NS(cached_tokens=1100)))),
        ])


def test_codex_client_drives_the_session(tmp_path):
    box = []
    client = codex.CodexClient(model="gpt-5.5", auth=_FakeAuth(), inner_factory=lambda tok: NS(responses=_Responses(box)))
    w = Workspace.open(FX, tmp_path / "ws")
    s = chat.Session(w, client=client, model_id="gpt-5.5")
    events = list(s.ask_stream("what does Margin % do?"))
    kinds = [e["type"] for e in events]
    assert kinds[0] == "tool" and events[0]["name"] == "get_object" and "tool_result" in kinds and kinds[-1] == "done"
    t = events[-1]["turn"]
    assert t["a"].startswith("`CAL04 Margin.Margin %` divides") and t["unverified"] == [] and t["tools"][0]["tool"] == "get_object"
    assert t["usage"]["calls"] == 2 and t["usage"]["cache_read"] == 1900 and t["usage"]["input"] == 300 and t["usage"]["cost_usd"] == 0
    assert box[0]["prompt_cache_key"] == box[1]["prompt_cache_key"]      # same estate prefix -> same cache route


def test_to_responses_shapes():
    system = [{"type": "text", "text": "A"}, {"type": "text", "text": "B", "cache_control": {"type": "ephemeral"}}]
    msgs = [{"role": "user", "content": [{"type": "text", "text": "hi", "cache_control": {"type": "ephemeral"}}]},
            {"role": "assistant", "content": [codex.TextBlock(text="thinking"), codex.ToolUseBlock(id="c9", name="find", input={"text": "x"})]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "c9", "content": "{}"}]}]
    ins, tools, items = codex.to_responses(system, [{"name": "find", "description": "d", "input_schema": {"type": "object", "properties": {}}}], msgs)
    assert ins == "A\n\nB" and tools[0]["parameters"]["type"] == "object"
    assert [i["type"] for i in items] == ["message", "message", "function_call", "function_call_output"]
    assert items[2]["arguments"] == '{"text": "x"}' and items[3]["call_id"] == "c9"
