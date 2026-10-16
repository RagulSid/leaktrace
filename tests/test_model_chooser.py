"""The model chooser behind an OpenAI-compatible chat API, tested against a fake server (httpx.MockTransport):
no request leaves this machine and no model is called.

What must hold: the request is the documented shape; timeouts, 429s and malformed answers fall back to the rule
chooser; the run never makes more model calls than its cap; and every step says which chooser really picked it.
"""

import json

import httpx
import pytest

from app import config
from app.agents import choosers, runtime
from app.agents.choosers import FallbackChooser, ModelChooser, RuleChooser, Step, ToolCall
from app.agents.llm_client import ChatClient, LLMBadOutput, LLMRateLimited, LLMTimeout, LLMUnavailable
from app.agents.roles import ROLES
from app.graph.client import TenantGraph
from scenario_generator.run import run
from tests.conftest import fresh_tenant

BASE = "https://fake.example/v1beta/openai/"
MODEL = "fake-model-1"


def tool_reply(name, args=None, call_id="c1"):
    return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
        {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(args or {})}}]}}]})


def text_reply(text):
    return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": text}}]})


class FakeServer:
    """Answers each POST with the next scripted response (or the result of a callable)."""

    def __init__(self, replies):
        self.replies, self.requests = list(replies), []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        r = self.replies.pop(0) if self.replies else httpx.Response(500, text="script ran out")
        return r(request) if callable(r) else r

    def client(self, **kw) -> ChatClient:
        return ChatClient(BASE, "test-key-not-real", MODEL, timeout_s=2, transport=httpx.MockTransport(self), **kw)


# ---------------------------------------------------------------- the HTTP client


def test_request_is_the_documented_shape_and_the_tool_call_is_read(monkeypatch):
    monkeypatch.setattr(config, "LLM_REASONING_EFFORT", None)
    srv = FakeServer([tool_reply("set_severity", {"level": "high"}, "abc")])
    reply = srv.client().chat([{"role": "user", "content": "hi"}],
                              tools=[{"type": "function", "function": {"name": "set_severity", "parameters": {}}}])
    req = srv.requests[0]
    assert str(req.url) == "https://fake.example/v1beta/openai/chat/completions"
    assert req.headers["authorization"] == "Bearer test-key-not-real"
    body = json.loads(req.content)
    assert body["model"] == MODEL and body["tool_choice"] == "auto" and body["max_tokens"] == config.LLM_MAX_TOKENS
    assert set(body) == {"model", "messages", "max_tokens", "tools", "tool_choice"}  # nothing undocumented
    assert reply.tool_calls == [{"id": "abc", "name": "set_severity", "args": {"level": "high"}}]


@pytest.mark.parametrize("response,error", [
    (httpx.Response(429, text="RESOURCE_EXHAUSTED"), LLMRateLimited),
    (httpx.Response(503, text="UNAVAILABLE: high demand"), LLMUnavailable),
    (httpx.Response(500, text="boom"), LLMBadOutput),
    (httpx.Response(200, text="not json"), LLMBadOutput),
    (httpx.Response(200, json={"choices": []}), LLMBadOutput),
    (httpx.Response(200, json={"choices": [{"message": {"tool_calls": [
        {"id": "x", "type": "function", "function": {"name": "f", "arguments": "{not json"}}]}}]}), LLMBadOutput),
    (httpx.Response(200, json={"choices": [{"message": {"tool_calls": [
        {"id": "x", "type": "function", "function": {"name": "f", "arguments": "[1, 2]"}}]}}]}), LLMBadOutput),
])
def test_failures_become_the_three_known_errors(response, error):
    with pytest.raises(error):
        FakeServer([response]).client().chat([{"role": "user", "content": "hi"}])


def test_timeout_becomes_llm_timeout():
    def slow(request):
        raise httpx.ReadTimeout("too slow", request=request)

    with pytest.raises(LLMTimeout):
        FakeServer([slow]).client().chat([{"role": "user", "content": "hi"}])


def test_client_needs_all_three_settings(monkeypatch):
    for k in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"):
        monkeypatch.setattr(config, k, None)
    with pytest.raises(ValueError):
        ChatClient()


# ---------------------------------------------------------------- the model chooser and its fallback


def test_messages_carry_the_history_as_tool_calls_and_results():
    role = ROLES["triage"]
    hist = [Step(ToolCall("t1", "look_at_problem", {}, chooser=MODEL), {"zones": ["Z-A"]})]
    msgs = ModelChooser.messages(role, {"problem": "INC-1"}, hist)
    assert [m["role"] for m in msgs] == ["system", "user", "assistant", "tool"]
    assert msgs[0]["content"] == role.prompt
    assert msgs[2]["tool_calls"][0] == {"id": "t1", "type": "function",
                                        "function": {"name": "look_at_problem", "arguments": "{}"}}
    assert msgs[3] == {"role": "tool", "tool_call_id": "t1", "content": json.dumps({"zones": ["Z-A"]})}
    specs = choosers.tool_specs(role)
    assert {s["function"]["name"] for s in specs} == set(role.tools)
    assert all(s["type"] == "function" and s["function"]["parameters"]["type"] == "object" for s in specs)


def test_model_step_is_labelled_with_the_model():
    srv = FakeServer([tool_reply("look_at_problem")])
    c = FallbackChooser(ModelChooser(srv.client()), max_calls=10)
    call = c.choose(ROLES["triage"], {}, [])
    assert (call.name, call.chooser, call.fallback) == ("look_at_problem", MODEL, None)


def test_rate_limit_hands_the_rest_of_the_run_to_the_rules():
    srv = FakeServer([httpx.Response(429, text="slow down")])
    c = FallbackChooser(ModelChooser(srv.client()), max_calls=10)
    first = c.choose(ROLES["triage"], {}, [])
    second = c.choose(ROLES["triage"], {}, [Step(first, {"zones": []})])
    assert (first.chooser, first.fallback) == ("rules", "rate_limited")
    assert (second.chooser, second.fallback) == ("rules", "rate_limited")
    assert len(srv.requests) == 1  # never asked again after the 429


def test_malformed_output_falls_back_for_that_step_only_then_stops_after_three():
    srv = FakeServer([text_reply("I would look at the problem"), tool_reply("look_at_problem"),
                      text_reply("x"), text_reply("y"), tool_reply("set_severity", {"level": "low"})])
    c = FallbackChooser(ModelChooser(srv.client()), max_calls=10)
    role = ROLES["triage"]
    labels = [(lambda call: (call.chooser, call.fallback))(c.choose(role, {}, [])) for _ in range(5)]
    assert labels == [("rules", "malformed_output"), (MODEL, None), ("rules", "malformed_output"),
                      ("rules", "malformed_output"), ("rules", "malformed_output")]
    assert len(srv.requests) == 4 and c.stopped == "malformed_output"


def test_call_cap_is_never_exceeded():
    srv = FakeServer([tool_reply("look_at_problem") for _ in range(10)])
    c = FallbackChooser(ModelChooser(srv.client()), max_calls=3)
    calls = [c.choose(ROLES["triage"], {}, []) for _ in range(5)]
    assert [x.chooser for x in calls] == [MODEL, MODEL, MODEL, "rules", "rules"]
    assert calls[3].fallback == "call_cap" and len(srv.requests) == 3


def test_report_prose_from_the_model_or_the_template():
    ok = FallbackChooser(ModelChooser(FakeServer([text_reply("Problem P is resolved. Practice data.")]).client()))
    assert ok.prose_writer({"id": "P"}) == ("Problem P is resolved. Practice data.", MODEL)
    limited = FallbackChooser(ModelChooser(FakeServer([httpx.Response(429)]).client()))
    assert limited.prose_writer({"id": "P"}) is None  # the report then says prose_by 'template'
    assert RuleChooser().prose_writer({"id": "P"}) is None


def test_default_is_the_rules_without_a_key(monkeypatch):
    for k in ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL"):
        monkeypatch.setattr(config, k, None)
    assert isinstance(choosers.default("auto"), RuleChooser)
    assert isinstance(choosers.default("rules"), RuleChooser)
    with pytest.raises(ValueError):
        choosers.default("model")
    monkeypatch.setattr(config, "LLM_BASE_URL", BASE)
    monkeypatch.setattr(config, "LLM_API_KEY", "test-key-not-real")
    monkeypatch.setattr(config, "LLM_MODEL", MODEL)
    c = choosers.default("auto")
    assert isinstance(c, FallbackChooser) and c.name == f"{MODEL} (fallback: rules)"
    assert isinstance(choosers.default("rules"), RuleChooser)


# ---------------------------------------------------------------- a real helper run, labelled honestly


def test_helper_run_records_which_chooser_picked_each_step():
    tenant = fresh_tenant()
    try:
        out = run("s1", tenant, seed=2, reset=True, password="practice-only-password", investigate=False)
        tg = TenantGraph(tenant)
        # the model does the Intake step well, then hits the free-tier limit
        srv = FakeServer([tool_reply("look_at_problem", {}, "m1"), tool_reply("suggested_severity", {}, "m2"),
                          tool_reply("set_severity", {"level": "high"}, "m3"),
                          tool_reply("pass_to_investigator", {"note": "leak alarm and a report"}, "m4"),
                          httpx.Response(429, text="RESOURCE_EXHAUSTED")])
        chooser = FallbackChooser(ModelChooser(srv.client()), max_calls=50)
        done = runtime.drain(tg, chooser, max_steps=3)  # intake, investigator, planner
        assert [d.kind for d in done] == ["triage", "investigate", "plan"]
        steps = [(r, t, json.loads(a)) for r, t, a in tg._g.ro_query(
            "MATCH (e:Episode {kind:'agent_step'})-[:OF]->(:Incident {id:$i}) RETURN e.actor, e.tool, e.args_json "
            "ORDER BY e.ts", {"i": out["incident"]}).result_set]
        intake = [(t, a["chooser"], a["fallback"]) for r, t, a in steps if r == "intake"]
        assert intake == [("look_at_problem", MODEL, None), ("suggested_severity", MODEL, None),
                          ("set_severity", MODEL, None), ("pass_to_investigator", MODEL, None)]
        later = [(a["chooser"], a["fallback"]) for r, t, a in steps if r != "intake"]
        assert later and set(later) == {("rules", "rate_limited")}  # never labelled as the model
        assert len(srv.requests) == 5
        assert tg._g.ro_query("MATCH (i:Incident {id:$i}) RETURN i.severity", {"i": out["incident"]}).result_set == [["high"]]
    finally:
        TenantGraph(tenant).delete()


def test_reasoning_effort_is_sent_only_when_set(monkeypatch):
    monkeypatch.setattr(config, "LLM_REASONING_EFFORT", None)
    srv = FakeServer([httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})] * 2)
    srv.client().chat([{"role": "user", "content": "hi"}])
    monkeypatch.setattr(config, "LLM_REASONING_EFFORT", "low")
    srv.client().chat([{"role": "user", "content": "hi"}])
    first, second = (json.loads(r.content) for r in srv.requests)
    assert "reasoning_effort" not in first and second["reasoning_effort"] == "low"


def test_thought_signature_goes_back_unchanged_and_rule_steps_go_back_as_text():
    sig = {"google": {"thought_signature": "opaque-signature-from-the-provider"}}
    first = httpx.Response(200, json={"choices": [{"message": {"tool_calls": [
        {"id": "a1", "type": "function", "extra_content": sig,
         "function": {"name": "look_at_problem", "arguments": "{}"}}]}}]})
    srv = FakeServer([first, tool_reply("set_severity", {"level": "high"}, "a2")])
    m = ModelChooser(srv.client())
    role = ROLES["triage"]
    call = m.choose(role, {"problem": "INC-1"}, [])
    assert call.extra == sig
    rules_step = Step(ToolCall("r1", "work_out_urgency", {}), {"severity": "high"})
    m.choose(role, {"problem": "INC-1"}, [Step(call, {"zones": ["Z-A"]}), rules_step])
    sent = json.loads(srv.requests[1].content)["messages"]
    assert sent[2]["tool_calls"][0]["extra_content"] == sig  # echoed exactly
    assert sent[4]["role"] == "user" and sent[4]["content"].startswith("Step already done by the fixed rules: work_out_urgency")
    assert all("tool_calls" not in x for x in sent[4:])

