"""The tool-calling conversation each protocol client keeps, with the network faked.

`_upstream.post_json` is replaced, as in GAM's provider tests: what matters is the body
each client sends and how it reads what comes back, round after round.
"""

import json

import httpx
import pytest

from app.models.provider import AIProvider
from app.providers import _upstream
from app.providers.anthropic import AnthropicProvider
from app.providers.base import Image, ProviderError, ToolResult, ToolSpec
from app.providers.openai import OpenAIProvider

SEARCH = ToolSpec(name="search_assets", description="Search GAM",
                  parameters={"type": "object", "properties": {"query": {"type": "string"}},
                              "required": ["query"]})


@pytest.fixture
def wire(monkeypatch):
    """Queue replies; record every request."""
    sent, queue = [], []

    def fake(url, *, headers=None, json_body, timeout, label, **kwargs):
        # A deep copy: the client appends to its history after the call, and the test
        # wants what was on the wire at the time.
        sent.append({"url": url, "headers": dict(headers or {}),
                     "body": json.loads(json.dumps(json_body))})
        return httpx.Response(200, json=queue.pop(0))

    monkeypatch.setattr(_upstream, "post_json", fake)
    return sent, queue


def row(**overrides):
    data = dict(user_id="u", name="Test", provider_type="anthropic", model="claude-opus-5-5",
                max_tokens=16000)
    data.update(overrides)
    return AIProvider(**data)


# ── Anthropic ────────────────────────────────────────────────────────────────

THINKING = {"type": "thinking", "thinking": "", "signature": "sig-abc"}


def test_an_anthropic_tool_loop_replays_the_assistant_turn_verbatim(wire):
    sent, queue = wire
    queue.append({
        "content": [THINKING, {"type": "text", "text": "Searching."},
                    {"type": "tool_use", "id": "t1", "name": "search_assets",
                     "input": {"query": "water"}}],
        "stop_reason": "tool_use",
        "usage": {"input_tokens": 100, "output_tokens": 20, "cache_read_input_tokens": 900},
    })
    queue.append({"content": [{"type": "text", "text": "Found two clips."}],
                  "stop_reason": "end_turn", "usage": {"input_tokens": 50, "output_tokens": 10}})

    chat = AnthropicProvider(row(), "sk").conversation(
        system=["REFERENCE", "PROJECT"], tools=[SEARCH],
        history=[("user", "Hi"), ("assistant", "Hello")], prompt="Find water")
    first = chat.ask()
    assert first.stop == "tool_use"
    assert [(c.id, c.name, c.arguments) for c in first.tool_calls] == [
        ("t1", "search_assets", {"query": "water"})]
    # Cache reads are billed input.
    assert (first.usage.input_tokens, first.usage.output_tokens) == (1000, 20)

    chat.answer([ToolResult("t1", '{"hits": 2}')])
    second = chat.ask()
    assert second.text == "Found two clips." and second.stop == "end"

    body = sent[1]["body"]
    assert sent[0]["url"] == "https://api.anthropic.com/v1/messages"
    assert body["model"] == "claude-opus-5-5"
    # Each system block a cache breakpoint; the conversation's end cached automatically.
    assert [b["text"] for b in body["system"]] == ["REFERENCE", "PROJECT"]
    assert all(b["cache_control"] == {"type": "ephemeral"} for b in body["system"])
    assert body["cache_control"] == {"type": "ephemeral"}
    assert body["tools"] == [{"name": "search_assets", "description": "Search GAM",
                              "input_schema": SEARCH.parameters}]
    # Nothing that current models reject.
    assert "tool_choice" not in body and "thinking" not in body
    roles = [m["role"] for m in body["messages"]]
    assert roles == ["user", "assistant", "user", "assistant", "user"]
    # The assistant's content exactly as it came, thinking block and signature included.
    assert body["messages"][3]["content"][0] == THINKING
    assert body["messages"][4]["content"] == [
        {"type": "tool_result", "tool_use_id": "t1", "content": '{"hits": 2}'}]


def test_every_result_goes_back_in_one_message_with_errors_flagged(wire):
    sent, queue = wire
    queue.append({"content": [{"type": "text", "text": "ok"}], "stop_reason": "end_turn",
                  "usage": {}})
    chat = AnthropicProvider(row(), "sk").conversation(system=[], tools=[SEARCH], history=[],
                                                      prompt="x")
    chat.answer([ToolResult("a", "fine"), ToolResult("b", "no such scene", is_error=True)])
    chat.ask()
    last = sent[0]["body"]["messages"][-1]
    assert last["role"] == "user"
    assert last["content"][1] == {"type": "tool_result", "tool_use_id": "b",
                                  "content": "no such scene", "is_error": True}


def test_a_compatible_gateway_gets_no_top_level_cache_field(wire):
    sent, queue = wire
    queue.append({"content": [{"type": "text", "text": "ok"}], "stop_reason": "end_turn"})
    chat = AnthropicProvider(row(provider_type="deepseek", use_anthropic_api=True,
                                 model="deepseek-chat"), "sk").conversation(
        system=["R"], tools=[], history=[], prompt="x")
    chat.ask()
    assert sent[0]["url"] == "https://api.deepseek.com/anthropic/v1/messages"
    assert "cache_control" not in sent[0]["body"]


def test_back_to_back_user_turns_are_merged_rather_than_refused(wire):
    sent, queue = wire
    queue.append({"content": [{"type": "text", "text": "ok"}], "stop_reason": "end_turn"})
    # A turn that failed before answering leaves two user messages in a row.
    AnthropicProvider(row(), "sk").conversation(
        system=[], tools=[], history=[("user", "first")], prompt="second").ask()
    assert sent[0]["body"]["messages"] == [{"role": "user", "content": "first\n\nsecond"}]


def test_a_refusal_is_an_error_naming_its_category(wire):
    _, queue = wire
    queue.append({"content": [], "stop_reason": "refusal", "stop_details": {"category": "cyber"}})
    with pytest.raises(ProviderError, match="declined.*cyber"):
        AnthropicProvider(row(), "sk").conversation(system=[], tools=[], history=[],
                                                    prompt="x").ask()


# ── OpenAI-compatible ────────────────────────────────────────────────────────

def test_an_openai_tool_loop(wire):
    sent, queue = wire
    queue.append({"choices": [{"finish_reason": "tool_calls", "message": {
        "role": "assistant", "content": None, "tool_calls": [
            {"id": "c1", "type": "function",
             "function": {"name": "search_assets", "arguments": '{"query": "water"}'}},
            {"id": "c2", "type": "function",
             "function": {"name": "search_assets", "arguments": "{not json"}}]}}],
        "usage": {"prompt_tokens": 70, "completion_tokens": 9}})
    queue.append({"choices": [{"finish_reason": "stop",
                               "message": {"role": "assistant", "content": "Done."}}]})

    chat = OpenAIProvider(row(provider_type="openai", model="gpt-4.1"), "sk").conversation(
        system=["REFERENCE", "PROJECT"], tools=[SEARCH], history=[], prompt="Find water")
    first = chat.ask()
    assert first.stop == "tool_use"
    assert first.tool_calls[0].arguments == {"query": "water"}
    # Unparseable arguments are kept as an error to hand back, never executed.
    assert first.tool_calls[1].parse_error and first.tool_calls[1].arguments == {}
    chat.answer([ToolResult("c1", "2 hits"), ToolResult("c2", "bad arguments", is_error=True)])
    assert chat.ask().text == "Done."

    body = sent[1]["body"]
    assert sent[0]["url"] == "https://api.openai.com/v1/chat/completions"
    assert sent[0]["headers"]["Authorization"] == "Bearer sk"
    assert body["messages"][0] == {"role": "system", "content": "REFERENCE\n\nPROJECT"}
    assert body["tools"][0] == {"type": "function", "function": {
        "name": "search_assets", "description": "Search GAM", "parameters": SEARCH.parameters}}
    assert body["messages"][2]["tool_calls"][0]["id"] == "c1"
    assert body["messages"][3:] == [
        {"role": "tool", "tool_call_id": "c1", "content": "2 hits"},
        {"role": "tool", "tool_call_id": "c2", "content": "ERROR: bad arguments"}]


def test_ollama_is_spoken_to_over_its_v1_endpoint_with_no_key(wire):
    sent, queue = wire
    queue.append({"choices": [{"finish_reason": "stop", "message": {"content": "hi"}}]})
    OpenAIProvider(row(provider_type="ollama", model="qwen3", base_url="http://10.0.0.5:11434"),
                   "").conversation(system=[], tools=[], history=[], prompt="x").ask()
    assert sent[0]["url"] == "http://10.0.0.5:11434/v1/chat/completions"
    assert "Authorization" not in sent[0]["headers"]


def test_a_server_that_says_stop_while_calling_a_tool_is_read_as_a_tool_call(wire):
    _, queue = wire
    queue.append({"choices": [{"finish_reason": "stop", "message": {"content": "", "tool_calls": [
        {"id": "c1", "function": {"name": "search_assets", "arguments": "{}"}}]}}]})
    reply = OpenAIProvider(row(provider_type="custom"), "sk").conversation(
        system=[], tools=[SEARCH], history=[], prompt="x").ask()
    assert reply.stop == "tool_use"


def test_a_provider_error_names_the_provider(monkeypatch):
    monkeypatch.setattr(_upstream, "post_json", lambda *a, **k: httpx.Response(
        401, json={"error": {"message": "bad key"}}))
    with pytest.raises(ProviderError, match="Test"):
        OpenAIProvider(row(provider_type="openai"), "sk").conversation(
            system=[], tools=[], history=[], prompt="x").ask()


# ── pictures ─────────────────────────────────────────────────────────────────

PICTURE = Image(media_type="image/png", data=b"\x89PNG", label="Image 1: board.png")


def test_anthropic_opens_with_the_pictures_and_folds_the_first_message_into_them(wire):
    sent, queue = wire
    queue.append({"content": [{"type": "text", "text": "A storyboard."}], "stop_reason": "end_turn",
                  "usage": {"input_tokens": 1, "output_tokens": 1}})
    conversation = AnthropicProvider(row(), "sk").conversation(
        system=["ref"], tools=[], history=[("user", "earlier"), ("assistant", "ok")],
        prompt="what is this?", images=[PICTURE])
    conversation.ask()
    first, second, third = sent[0]["body"]["messages"]
    # Still alternating: the first history message joins the pictures' own message.
    assert first["role"] == "user" and second["role"] == "assistant" and third["role"] == "user"
    assert first["content"][0] == {"type": "text", "text": "Image 1: board.png"}
    assert first["content"][1] == {"type": "image", "source": {
        "type": "base64", "media_type": "image/png", "data": "iVBORw=="}}
    assert first["content"][2] == {"type": "text", "text": "earlier"}


def test_openai_sends_pictures_as_data_url_parts(wire):
    sent, queue = wire
    queue.append({"choices": [{"message": {"role": "assistant", "content": "A board."},
                               "finish_reason": "stop"}],
                  "usage": {"prompt_tokens": 1, "completion_tokens": 1}})
    OpenAIProvider(row(provider_type="openai", model="gpt-5"), "sk").conversation(
        system=["ref"], tools=[], history=[], prompt="what is this?", images=[PICTURE]).ask()
    system, pictures, prompt = sent[0]["body"]["messages"]
    assert pictures["role"] == "user"
    assert pictures["content"][1] == {"type": "image_url",
                                      "image_url": {"url": "data:image/png;base64,iVBORw=="}}
    assert prompt == {"role": "user", "content": "what is this?"}
