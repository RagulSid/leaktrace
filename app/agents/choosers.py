"""How a helper picks its next tool.

  RuleChooser      a fixed, deterministic offline rule list per role (app/agents/roles.py). The default when no
                   model is configured, and the fallback whenever the model cannot answer.
  ModelChooser     a language model behind any OpenAI-compatible chat API (app/agents/llm_client.py). It sees the
                   helper's instructions, the task and every earlier tool result, and must call one tool per turn.
  FallbackChooser  what a run actually uses when a model is configured: the model, with the rules taking over on
                   a timeout, a 429, malformed output, or when the run's call cap is reached.

Every tool call carries the name of the chooser that really produced it ("rules" or the model name) and, after
a fallback, why. The runtime records that on each step, so a rule step is never labelled as a model step.

Neither chooser can do anything the code does not allow: a helper only has its own tools, and every tool checks
roles, states and authority itself (app/agents/roles.py, app/execution/service.py).
"""

import json
from dataclasses import dataclass, field

from app import config
from app.agents.llm_client import ChatClient, LLMBadOutput, LLMError


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict = field(default_factory=dict)
    chooser: str = "rules"  # who actually chose this call: "rules" or the model name
    fallback: str | None = None  # why the rules chose it although a model is configured
    extra: dict | None = None  # the provider's extra_content for this call, echoed back unchanged


@dataclass
class Step:
    call: ToolCall
    result: dict


class RuleChooser:
    name = "rules"

    def choose(self, role, brief: dict, history: list[Step]) -> ToolCall | None:
        picked = role.rules(brief, history)
        if picked is None:
            return None
        name, args = picked
        return ToolCall(f"call_{len(history)}", name, args)

    def prose_writer(self, facts: dict):
        return None  # the incident report uses its fixed template


def tool_specs(role) -> list[dict]:
    return [{"type": "function", "function": {"name": t.name, "description": t.description,
                                              "parameters": t.spec()["input_schema"]}} for t in role.tools.values()]


class ModelChooser:
    """Tool choice by a language model through an OpenAI-compatible chat API."""

    def __init__(self, client: ChatClient):
        self.client = client
        self.name = client.model

    @staticmethod
    def messages(role, brief: dict, history: list[Step]) -> list[dict]:
        """The task, then each earlier step. A step the model chose goes back as its own tool call, with the
        provider's extra_content unchanged (Gemini 3 thinking models reject a tool call without its thought
        signature: HTTP 400, seen 2026-10-16). A step the rules chose was never a model tool call, so it goes back
        as plain text the model can read."""
        msgs = [{"role": "system", "content": role.prompt},
                {"role": "user", "content": "Your task:\n" + json.dumps(brief, default=str, sort_keys=True)[:12000]}]
        for st in history:
            result = json.dumps(st.result, default=str, sort_keys=True)[:12000]
            if st.call.chooser == "rules":
                msgs.append({"role": "user", "content": f"Step already done by the fixed rules: {st.call.name} "
                             f"{json.dumps(st.call.args, default=str)}. Result: {result}"})
                continue
            call = {"id": st.call.id, "type": "function",
                    "function": {"name": st.call.name, "arguments": json.dumps(st.call.args, default=str)}}
            if st.call.extra:
                call["extra_content"] = st.call.extra
            msgs.append({"role": "assistant", "content": "", "tool_calls": [call]})
            msgs.append({"role": "tool", "tool_call_id": st.call.id, "content": result})
        return msgs

    def choose(self, role, brief: dict, history: list[Step]) -> ToolCall:
        reply = self.client.chat(self.messages(role, brief, history), tools=tool_specs(role))
        if not reply.tool_calls:
            raise LLMBadOutput("the model answered without calling a tool")
        c = reply.tool_calls[0]
        return ToolCall(c["id"], c["name"], c["args"], chooser=self.name, extra=c.get("extra"))

    def prose(self, facts: dict) -> str:
        reply = self.client.chat([
            {"role": "system", "content": "Write a short incident report in plain words for a facilities team. Use "
                                          "only the facts given. Do not add numbers, causes or outcomes that are not "
                                          "in the facts. Say it is practice data."},
            {"role": "user", "content": json.dumps(facts, default=str, sort_keys=True)[:20000]}])
        if not reply.text.strip():
            raise LLMBadOutput("empty report text")
        return reply.text.strip()


class FallbackChooser:
    """The model, with the rule chooser taking over. A timeout or a 429 hands the rest of the run to the rules
    (no retry storm against a rate limit); malformed output hands over that one step, and the third one the rest
    of the run. The run never makes more than `max_calls` model calls."""

    MAX_MALFORMED = 3

    def __init__(self, model: ModelChooser, max_calls: int | None = None):
        self.model, self.rules = model, RuleChooser()
        self.max_calls = config.LLM_MAX_CALLS_PER_RUN if max_calls is None else max_calls
        self.name = f"{model.name} (fallback: rules)"
        self.calls, self.malformed = 0, 0
        self.stopped: str | None = None  # why the model is no longer asked in this run
        self.fallbacks: list[dict] = []

    def _ask(self, fn, *args):
        if self.stopped is None and self.calls >= self.max_calls:
            self.stopped = "call_cap"
        if self.stopped is not None:
            return None, self.stopped
        self.calls += 1
        try:
            return fn(*args), None
        except LLMError as e:
            if isinstance(e, LLMBadOutput):
                self.malformed += 1
                if self.malformed >= self.MAX_MALFORMED:
                    self.stopped = e.reason
            else:
                self.stopped = e.reason
            self.fallbacks.append({"reason": e.reason, "detail": str(e)[:200]})
            return None, e.reason

    def choose(self, role, brief: dict, history: list[Step]) -> ToolCall | None:
        call, why = self._ask(self.model.choose, role, brief, history)
        if call is not None:
            return call
        call = self.rules.choose(role, brief, history)
        if call is not None:
            call.fallback = why
        return call

    def prose_writer(self, facts: dict):
        text, _ = self._ask(self.model.prose, facts)
        return (text, self.model.name) if text else None


def model_configured() -> bool:
    return bool(config.LLM_BASE_URL and config.LLM_API_KEY and config.LLM_MODEL)


def default(mode: str | None = None):
    """'rules', 'model' (alias 'llm'), or 'auto': the model (with rule fallback) when LLM_BASE_URL, LLM_API_KEY
    and LLM_MODEL are all set, otherwise the rules."""
    mode = mode or config.AGENT_CHOOSER
    if mode == "rules" or (mode == "auto" and not model_configured()):
        return RuleChooser()
    if not model_configured():
        raise ValueError("a model chooser needs LLM_BASE_URL, LLM_API_KEY and LLM_MODEL")
    return FallbackChooser(ModelChooser(ChatClient()))
