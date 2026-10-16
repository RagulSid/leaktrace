"""How a helper picks its next tool.

  LLMChooser    a language model (Anthropic Messages API, tool use). It sees the helper's instructions, the
                task and every earlier tool result, and must call exactly one of the helper's tools per turn.
  RuleChooser   a fixed, deterministic offline chooser: each role has a short rule list (app/agents/roles.py).
                Used when no model is configured, and in tests so they are repeatable. It is labelled as such
                on every step it takes; it is not presented as a model.

Neither one can do anything the code does not allow: a helper only has its own tools, and every tool checks
roles, states and authority itself (app/agents/roles.py, app/execution/service.py).
"""

import json
import os
from dataclasses import dataclass, field

from app import config


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict = field(default_factory=dict)


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

    prose_writer = None  # the incident report uses its fixed template


class LLMChooser:
    """Tool choice with a language model. Needs ANTHROPIC_API_KEY (and the `anthropic` package)."""

    def __init__(self, client=None, model: str | None = None):
        if client is None:
            import anthropic

            client = anthropic.Anthropic()
        self.client, self.model = client, model or config.LLM_MODEL
        self.name = f"llm:{self.model}"

    def _messages(self, brief: dict, history: list[Step]) -> list[dict]:
        msgs = [{"role": "user", "content": "Your task:\n" + json.dumps(brief, default=str, sort_keys=True)[:12000]}]
        for st in history:
            msgs.append({"role": "assistant", "content": [
                {"type": "tool_use", "id": st.call.id, "name": st.call.name, "input": st.call.args}]})
            msgs.append({"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": st.call.id,
                 "content": json.dumps(st.result, default=str, sort_keys=True)[:12000],
                 "is_error": "refused" in st.result}]})
        return msgs

    def choose(self, role, brief: dict, history: list[Step]) -> ToolCall | None:
        resp = self.client.messages.create(
            model=self.model, max_tokens=config.LLM_MAX_TOKENS, system=role.prompt,
            tools=[t.spec() for t in role.tools.values()],
            tool_choice={"type": "any", "disable_parallel_tool_use": True},
            messages=self._messages(brief, history),
        )
        for block in resp.content:
            if block.type == "tool_use":
                return ToolCall(block.id, block.name, dict(block.input or {}))
        return None

    def prose_writer(self, facts: dict) -> str:
        resp = self.client.messages.create(
            model=self.model, max_tokens=config.LLM_MAX_TOKENS,
            system=("Write a short incident report in plain words for a facilities team. Use only the facts given. "
                    "Do not add numbers, causes or outcomes that are not in the facts. Say it is practice data."),
            messages=[{"role": "user", "content": json.dumps(facts, default=str, sort_keys=True)[:20000]}],
        )
        return "".join(b.text for b in resp.content if b.type == "text").strip()


def default(mode: str | None = None):
    mode = mode or config.AGENT_CHOOSER
    if mode == "rules" or (mode == "auto" and not os.getenv("ANTHROPIC_API_KEY")):
        return RuleChooser()
    return LLMChooser()
