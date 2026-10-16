"""A small client for any OpenAI-compatible chat API (POST {LLM_BASE_URL}/chat/completions).

Configured only by LLM_BASE_URL, LLM_API_KEY and LLM_MODEL. No vendor SDK: plain HTTPS through httpx, with a
short timeout. Every failure is turned into one of four errors the helpers know how to fall back from:

  LLMTimeout      the request timed out or the connection failed
  LLMRateLimited  HTTP 429 (free tiers return this when a per-minute or per-day limit is reached)
  LLMUnavailable  HTTP 503 (the provider is overloaded for a while: "high demand")
  LLMBadOutput    any other non-200 answer, a body that is not the expected JSON, or tool-call arguments
                  that are not a JSON object

Only parameters documented for Google AI Studio's OpenAI-compatible endpoint are sent: model, messages,
tools ({"type": "function", ...}), tool_choice "auto" (checked 2026-10-15, see repo decisions D-066), and
reasoning_effort only when LEAKTRACE_LLM_REASONING_EFFORT is set (thinking models otherwise spend seconds and
tokens thinking before a short answer).
"""

import json
from dataclasses import dataclass

import httpx

from app import config


class LLMError(Exception):
    reason = "error"


class LLMTimeout(LLMError):
    reason = "timeout"


class LLMRateLimited(LLMError):
    reason = "rate_limited"


class LLMUnavailable(LLMError):
    reason = "unavailable"


class LLMBadOutput(LLMError):
    reason = "malformed_output"


@dataclass
class ChatReply:
    text: str
    tool_calls: list[dict]  # [{"id", "name", "args"}]


class ChatClient:
    def __init__(self, base_url: str | None = None, api_key: str | None = None, model: str | None = None,
                 timeout_s: float | None = None, transport: httpx.BaseTransport | None = None):
        self.base_url = (base_url or config.LLM_BASE_URL or "").rstrip("/")
        self.api_key = api_key or config.LLM_API_KEY
        self.model = model or config.LLM_MODEL
        if not (self.base_url and self.api_key and self.model):
            raise ValueError("LLM_BASE_URL, LLM_API_KEY and LLM_MODEL must all be set")
        self._http = httpx.Client(timeout=timeout_s or config.LLM_TIMEOUT_S, transport=transport)

    def chat(self, messages: list[dict], tools: list[dict] | None = None, max_tokens: int | None = None) -> ChatReply:
        body = {"model": self.model, "messages": messages, "max_tokens": max_tokens or config.LLM_MAX_TOKENS}
        if config.LLM_REASONING_EFFORT:
            body["reasoning_effort"] = config.LLM_REASONING_EFFORT
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        try:
            r = self._http.post(f"{self.base_url}/chat/completions", json=body,
                                headers={"Authorization": f"Bearer {self.api_key}"})
        except (httpx.TimeoutException, httpx.TransportError) as e:
            raise LLMTimeout(str(e)) from e
        if r.status_code == 429:
            raise LLMRateLimited(r.text[:300])
        if r.status_code == 503:
            raise LLMUnavailable(r.text[:300])
        if r.status_code != 200:
            raise LLMBadOutput(f"HTTP {r.status_code}: {r.text[:300]}")
        try:
            msg = r.json()["choices"][0]["message"]
            calls = []
            for c in msg.get("tool_calls") or []:
                args = c["function"].get("arguments") or "{}"
                args = json.loads(args) if isinstance(args, str) else args
                if not isinstance(args, dict):
                    raise ValueError("tool arguments are not an object")
                call = {"id": c.get("id") or f"call_{len(calls)}", "name": c["function"]["name"], "args": args}
                if c.get("extra_content"):  # provider data to send back unchanged (Gemini 3: the thought signature)
                    call["extra"] = c["extra_content"]
                calls.append(call)
            return ChatReply(msg.get("content") or "", calls)
        except (KeyError, IndexError, TypeError, ValueError) as e:
            raise LLMBadOutput(f"unexpected reply: {e}") from e
