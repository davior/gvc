"""The OpenAI chat-completions protocol, with tools.

Serves `openai`, `custom`, `deepseek` (unless pointed at its Anthropic endpoint) and
`ollama`, whose `/v1` endpoint speaks the same protocol, tools included. One client for
all four, named for the protocol rather than a vendor.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Sequence, Tuple

from app.providers import PROVIDER_OLLAMA, _upstream
from app.providers.base import ProviderError, Reply, ToolCall, ToolResult, ToolSpec, Usage
from app.providers.endpoints import OLLAMA_BASE, openai_compat_base
from app.providers.params import parse_extra_params

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 300.0
# A local model on modest hardware takes minutes per answer, not seconds.
OLLAMA_TIMEOUT = 900.0

_STOPS = {"stop": "end", "tool_calls": "tool_use", "length": "max_tokens",
          "content_filter": "refusal", "function_call": "tool_use"}


class OpenAIProvider:
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
                     history: Sequence[Tuple[str, str]], prompt: str) -> "OpenAIConversation":
        return OpenAIConversation(self._provider, self._api_key, system, tools, history, prompt)


class OpenAIConversation:
    def __init__(self, provider, api_key: str, system: Sequence[str], tools: Sequence[ToolSpec],
                 history: Sequence[Tuple[str, str]], prompt: str):
        self._provider = provider
        self._api_key = api_key
        self._tools = [{"type": "function", "function": {
            "name": t.name, "description": t.description, "parameters": t.parameters}}
            for t in tools]
        # One system message: this protocol has no blocks, and its providers cache the
        # longest stable prefix on their own.
        self.messages: List[Dict[str, Any]] = []
        joined = "\n\n".join(text for text in system if text)
        if joined:
            self.messages.append({"role": "system", "content": joined})
        for role, text in history:
            self.messages.append({"role": role, "content": text})
        self.messages.append({"role": "user", "content": prompt})

    def _url_and_timeout(self) -> Tuple[str, float]:
        if self._provider.provider_type == PROVIDER_OLLAMA:
            base = (self._provider.base_url or OLLAMA_BASE).rstrip("/")
            return f"{base}/v1/chat/completions", OLLAMA_TIMEOUT
        base = openai_compat_base(self._provider.provider_type, self._provider.base_url)
        return f"{base}/v1/chat/completions", REQUEST_TIMEOUT

    def ask(self) -> Reply:
        body: Dict[str, Any] = {
            "model": self._provider.model,
            "max_tokens": self._provider.max_tokens,
            "messages": self.messages,
        }
        if self._tools:
            body["tools"] = self._tools
        body.update(parse_extra_params(self._provider.extra_params))
        url, timeout = self._url_and_timeout()
        headers = {"content-type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        response = _upstream.post_json(url, headers=headers, json_body=body, timeout=timeout,
                                       label=self._provider.name)
        if response.status_code >= 400:
            raise ProviderError(f"{self._provider.name}: {_upstream.error_detail(response)}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderError(f"{self._provider.name} returned a response that was not JSON") from exc
        reply, message = parse_response(payload, model=self._provider.model,
                                        provider_type=self._provider.provider_type)
        self.messages.append(message)
        return reply

    def answer(self, results: Sequence[ToolResult]) -> None:
        for r in results:
            # No error flag in this protocol: an error is said in the content.
            self.messages.append({"role": "tool", "tool_call_id": r.call_id,
                                  "content": ("ERROR: " + r.content) if r.is_error else r.content})


def parse_response(payload: Any, *, model: str, provider_type: str) -> Tuple[Reply, Dict[str, Any]]:
    """The reply, and the assistant message to append to the history as it came."""
    if not isinstance(payload, dict) or not isinstance(payload.get("choices"), list) \
            or not payload["choices"]:
        raise ProviderError("The provider returned no choices")
    first = payload["choices"][0] if isinstance(payload["choices"][0], dict) else {}
    message = first.get("message") if isinstance(first.get("message"), dict) else {}
    calls: List[ToolCall] = []
    for raw in message.get("tool_calls") or []:
        function = raw.get("function") or {}
        try:
            arguments = json.loads(function.get("arguments") or "{}")
            error = None if isinstance(arguments, dict) else "arguments were not an object"
        except ValueError as exc:
            arguments, error = {}, f"arguments were not valid JSON ({exc})"
        calls.append(ToolCall(id=str(raw.get("id", "")), name=str(function.get("name", "")),
                              arguments=arguments if isinstance(arguments, dict) else {},
                              parse_error=error))
    stop = _STOPS.get(first.get("finish_reason"), "other")
    if calls and stop == "end":
        # Some compatible servers say "stop" even when they called a tool.
        stop = "tool_use"
    if stop == "refusal":
        raise ProviderError("The provider's content filter declined this request")
    text = message.get("content")
    text = text.strip() if isinstance(text, str) else ""

    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}

    def count(key: str) -> int:
        try:
            return int(usage.get(key, 0) or 0)
        except (TypeError, ValueError):
            return 0

    input_tokens, output_tokens = count("prompt_tokens"), count("completion_tokens")
    if not (input_tokens or output_tokens):
        # Some servers report only a total; counted as input, the cheaper side, so the
        # estimate errs low rather than inventing spend.
        input_tokens = count("total_tokens")
    # What goes back into the history: role, content and tool calls, nothing else a
    # server might reject on the way back in.
    echoed: Dict[str, Any] = {"role": "assistant", "content": message.get("content")}
    if message.get("tool_calls"):
        echoed["tool_calls"] = message["tool_calls"]
    return Reply(text=text, tool_calls=calls, stop=stop,
                 usage=Usage(input_tokens=input_tokens, output_tokens=output_tokens),
                 model=model, provider_type=provider_type), echoed
