"""What a chat provider has to do for the assistant: a conversation that can call tools.

GAM's provider layer (which this package is copied from) is one prompt in, one answer
out, because its callers each ask one question. The assistant is an agent: it searches
the library, edits the spec, reads the issues its edit produced and fixes them, all in
one turn. So the unit here is a `Conversation`, which owns its message history in the
provider's own wire format and grows it append-only.

Append-only is load-bearing, not tidiness. Anthropic's current models return thinking
blocks that must be replayed exactly as they came for the rest of the turn; a history
rebuilt from a neutral format each round would drop or alter them. So each adapter keeps
what the provider sent and only ever appends to it.
"""

from __future__ import annotations

from base64 import b64encode
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, Sequence, Tuple


class ProviderError(Exception):
    """The provider refused, failed, or returned something unusable."""


class ProviderUnavailable(ProviderError):
    """No usable provider is configured for this user: the fix is Settings, not a retry."""


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    # JSON Schema of the arguments.
    parameters: Dict[str, Any]


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: Dict[str, Any]
    # Set when the model's arguments were not a JSON object; handed back as an error
    # result so it can try again, never executed.
    parse_error: Optional[str] = None


@dataclass(frozen=True)
class ToolResult:
    call_id: str
    content: str
    is_error: bool = False


@dataclass
class Reply:
    text: str
    tool_calls: List[ToolCall] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    # end | tool_use | max_tokens | refusal | other
    stop: str = "end"
    model: str = ""
    # The provider's own type, not the protocol it spoke: DeepSeek over the Anthropic
    # endpoint is DeepSeek spend.
    provider_type: str = ""


class Conversation(Protocol):
    def ask(self) -> Reply:
        """Send the history so far and return what the model said next."""
        ...

    def answer(self, results: Sequence[ToolResult]) -> None:
        """Append the results of the tool calls in the last reply, all in one message."""
        ...

    def tell(self, text: str) -> None:
        """Append a user message after a reply that called no tools."""
        ...


@dataclass
class Image:
    """A picture the model is shown, as bytes it can read (JPEG, PNG, WebP or GIF)."""

    media_type: str
    data: bytes
    # How the text refers to it ("image 1: diagram.png"), said beside it.
    label: str

    def base64(self) -> str:
        return b64encode(self.data).decode("ascii")


class ChatProvider(Protocol):
    @property
    def model(self) -> str: ...

    @property
    def provider_type(self) -> str: ...

    def conversation(
        self, *, system: Sequence[str], tools: Sequence[ToolSpec],
        history: Sequence[Tuple[str, str]], prompt: str, images: Sequence[Image] = (),
    ) -> Conversation:
        """A new conversation.

        `system` is a list of blocks, most stable first: a provider that caches prompts
        breaks after each. `history` is earlier (role, text) turns, roles "user" and
        "assistant"; `prompt` is the user's new message. `images` open the conversation,
        ahead of the history: system prompts take text only, and at the start they stay
        part of the same cached prefix on every turn. Only passed to a provider marked
        as able to see images.
        """
        ...
