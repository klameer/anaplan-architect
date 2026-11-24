"""OpenAI with an API key goes over the Responses API (first hosted question, 2026-11-14: gpt-6.1-sol refused function
tools on chat completions). Other endpoints keep chat completions."""
from types import SimpleNamespace as NS
from anaplan_architect import provider
from anaplan_architect.openai_compat import ChatClient, ResponsesClient


class FakeResponses:
    def __init__(self, events, fail_on_reasoning=False):
        self.events = events; self.calls = []; self.fail_on_reasoning = fail_on_reasoning

    def create(self, **kw):
        self.calls.append(kw)
        if self.fail_on_reasoning and "reasoning" in kw:
            raise RuntimeError("Unsupported parameter: reasoning.effort")
        return iter(self.events)


def _events():
    usage = NS(input_tokens=120, output_tokens=30, input_tokens_details=NS(cached_tokens=20))
    return [NS(type="response.output_text.delta", delta="Looking. "),
            NS(type="response.output_item.added", output_index=1, item=NS(type="function_call", call_id="call_1", name="query_line_items", arguments="")),
            NS(type="response.function_call_arguments.delta", output_index=1, delta='{"model": "FP&A"}'),
            NS(type="response.output_item.done", output_index=1, item=NS(type="function_call", call_id="call_1", name="query_line_items", arguments='{"model": "FP&A"}')),
            NS(type="response.completed", response=NS(usage=usage))]


TOOLS = [{"name": "query_line_items", "description": "count", "input_schema": {"type": "object", "properties": {"model": {"type": "string"}}}}]


def test_a_question_with_tools_goes_over_the_responses_api_and_comes_back_in_the_sessions_shape():
    inner = NS(responses=FakeResponses(_events()))
    c = ResponsesClient("gpt-6.1-sol", inner=inner)
    with c.messages.stream(model="gpt-6.1-sol", system=[{"type": "text", "text": "You are the architect."}], tools=TOOLS,
                           messages=[{"role": "user", "content": "How many line items?"}], max_tokens=8000) as st:
        deltas = [e.delta.text for e in st if e.type == "content_block_delta"]
        msg = st.get_final_message()
    sent = inner.responses.calls[0]
    assert sent["stream"] is True and sent["store"] is False and sent["reasoning"] == {"effort": "medium"}
    assert sent["tools"][0] == {"type": "function", "name": "query_line_items", "description": "count", "parameters": TOOLS[0]["input_schema"]}
    assert sent["max_output_tokens"] == 32000 and "messages" not in sent       # a limit four times the answer's, so reasoning cannot cut it short; not the chat shape
    assert deltas == ["Looking. "] and msg.stop_reason == "tool_use"
    assert [b.type for b in msg.content] == ["text", "tool_use"] and msg.content[1].input == {"model": "FP&A"} and msg.content[1].id == "call_1"
    assert (msg.usage.input_tokens, msg.usage.cache_read_input_tokens, msg.usage.output_tokens) == (100, 20, 30)


def test_a_model_that_does_not_reason_is_asked_again_without_the_setting():
    inner = NS(responses=FakeResponses(_events(), fail_on_reasoning=True))
    c = ResponsesClient("gpt-4.1", inner=inner)
    with c.messages.stream(system="s", tools=TOOLS, messages=[{"role": "user", "content": "q"}]) as st:
        list(st)
    assert len(inner.responses.calls) == 2 and "reasoning" not in inner.responses.calls[1]


def test_openai_itself_is_called_over_responses_and_any_other_endpoint_over_chat(monkeypatch):
    for k in ("ANTHROPIC_API_KEY", "OPENAI_BASE_URL", "OPENAI_API", "OPENAI_REASONING"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("ARCHITECT_PROVIDER", "openai"); monkeypatch.setenv("ARCHITECT_MODEL", "gpt-6.1-sol"); monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-real")
    b = provider.resolve()
    assert b["provider"] == "openai" and isinstance(provider.client_kw(b)["client"], ResponsesClient)
    monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:11434/v1")
    assert isinstance(provider.client_kw(provider.resolve())["client"], ChatClient)
    monkeypatch.setenv("OPENAI_API", "responses")
    assert isinstance(provider.client_kw(provider.resolve())["client"], ResponsesClient)
    monkeypatch.setenv("OPENAI_API", "soap")
    assert provider.resolve()["provider"] == "none"
