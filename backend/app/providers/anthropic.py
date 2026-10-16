"""The Anthropic Messages protocol, with tools.

Serves `anthropic`, and `deepseek` or a `custom` gateway with `use_anthropic_api` set
(see `endpoints.py`). Raw httpx like the rest of the suite's provider code, because one
layer has to speak four vendors' protocols and the others have no Anthropic SDK to hand.

Two rules from the current API shape this:
- The assistant's content goes back exactly as it arrived, thinking blocks included,
  for every later request in the turn (`base.py` says why).
- Nothing forces a tool or switches thinking off: on current models a forced
  `tool_choice` and a disabled-thinking setting are both rejected, so the defaults
  (`auto`, adaptive thinking) are left alone and the prompt does the steering.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Sequence, Tuple

from app.providers import PROVIDER_ANTHROPIC, _upstream
from app.providers.base import ProviderError, Reply, ToolCall, ToolResult, ToolSpec, Usage
from app.providers.endpoints import anthropic_base, anthropic_headers
from app.providers.params import parse_extra_params

logger = logging.getLogger(__name__)

# A whole first draft can be several thousand tokens of tool input, generated before a
# byte comes back. Connect and write stay short in `_upstream`, so a dead endpoint still
# fails fast.
REQUEST_TIMEOUT = 300.0

_STOPS = {"end_turn": "end", "tool_use": "tool_use", "max_tokens": "max_tokens",
          "refusal": "refusal", "stop_sequence": "end"}


class AnthropicProvider:
    def __init__(self, provider, api_key: str):
        self._provider = provider
        self._api_key = api_key

    @property
    def model(self) -> str:
        return self._provider.model

    @property
    def provider_type(self) -> str:
        return self._provider.provider_type

    def conversation(self, *, system: Sequence[str], tools: Sequence[ToolSpec],
                     history: Sequence[Tuple[str, str]], prompt: str) -> "AnthropicConversation":
        return AnthropicConversation(self._provider, self._api_key, system, tools, history, prompt)


class AnthropicConversation:
    def __init__(self, provider, api_key: str, system: Sequence[str], tools: Sequence[ToolSpec],
                 history: Sequence[Tuple[str, str]], prompt: str):
        self._provider = provider
        self._api_key = api_key
        # Each system block is a cache breakpoint: the reference first (never changes),
        # then the project context (fixed for the whole turn). Anthropic allows four.
        self._system = [{"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}
                        for text in system[:3] if text]
        self._tools = [{"name": t.name, "description": t.description, "input_schema": t.parameters}
                       for t in tools]
        self.messages: List[Dict[str, Any]] = []
        for role, text in history:
            self._push(role, text)
        self._push("user", prompt)

    def _push(self, role: str, text: str) -> None:
        # The API wants turns to alternate; two of the same role in a row (a turn that
        # failed before answering) are merged rather than sent as a 400.
        if self.messages and self.messages[-1]["role"] == role and isinstance(
                self.messages[-1]["content"], str):
            self.messages[-1]["content"] += "\n\n" + text
        else:
            self.messages.append({"role": role, "content": text})

    def _body(self) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "model": self._provider.model,
            "max_tokens": self._provider.max_tokens,
            "messages": self.messages,
        }
        if self._system:
            body["system"] = self._system
        if self._tools:
            body["tools"] = self._tools
        if self._provider.provider_type == PROVIDER_ANTHROPIC:
            # Top-level caching moves its breakpoint to the end of the conversation each
            # round, so a long tool loop re-reads its history at the cached rate. Only
            # for Anthropic itself: a compatible gateway may not know the field.
            body["cache_control"] = {"type": "ephemeral"}
        body.update(parse_extra_params(self._provider.extra_params))
        return body

    def ask(self) -> Reply:
        response = _upstream.post_json(
            f"{anthropic_base(self._provider)}/v1/messages",
            headers=anthropic_headers(self._api_key, self._provider.provider_type),
            json_body=self._body(), timeout=REQUEST_TIMEOUT, label=self._provider.name,
        )
        if response.status_code >= 400:
            raise ProviderError(f"{self._provider.name}: {_upstream.error_detail(response)}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderError(f"{self._provider.name} returned a response that was not JSON") from exc
        reply = parse_response(payload, model=self._provider.model,
                               provider_type=self._provider.provider_type)
        content = payload.get("content") if isinstance(payload, dict) else None
        # Verbatim, thinking blocks and all.
        self.messages.append({"role": "assistant", "content": content or []})
        return reply

    def answer(self, results: Sequence[ToolResult]) -> None:
        # Every result in one user message: splitting them teaches the model to stop
        # calling tools in parallel.
        self.messages.append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": r.call_id, "content": r.content,
             **({"is_error": True} if r.is_error else {})}
            for r in results
        ]})


def parse_response(payload: Any, *, model: str, provider_type: str) -> Reply:
    if not isinstance(payload, dict) or not isinstance(payload.get("content"), list):
        raise ProviderError("The provider returned a message with no content")
    text_parts: List[str] = []
    calls: List[ToolCall] = []
    for block in payload["content"]:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            text_parts.append(block.get("text", ""))
        elif block.get("type") == "tool_use":
            arguments = block.get("input")
            calls.append(ToolCall(
                id=str(block.get("id", "")), name=str(block.get("name", "")),
                arguments=arguments if isinstance(arguments, dict) else {},
                parse_error=None if isinstance(arguments, dict) else "arguments were not an object",
            ))
    stop = _STOPS.get(payload.get("stop_reason"), "other")
    if stop == "refusal":
        details = payload.get("stop_details") or {}
        raise ProviderError("The model declined this request"
                            + (f" ({details.get('category')})" if details.get("category") else ""))

    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}

    def count(key: str) -> int:
        try:
            return int(usage.get(key, 0) or 0)
        except (TypeError, ValueError):
            return 0

    # Cache reads and writes are billed input; dropping them would make a cached turn
    # look nearly free.
    return Reply(
        text="".join(text_parts).strip(), tool_calls=calls, stop=stop,
        usage=Usage(input_tokens=count("input_tokens") + count("cache_read_input_tokens")
                    + count("cache_creation_input_tokens"),
                    output_tokens=count("output_tokens")),
        model=model, provider_type=provider_type,
    )


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)
