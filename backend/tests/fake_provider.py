"""A chat provider that plays back a script, for running whole assistant turns offline.

Each scripted reply is a `Reply`; the fake records what it was told (tool results and
mid-turn messages) so a test can assert on the conversation as well as the outcome.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.providers.base import Reply, ToolCall, ToolResult, ToolSpec, Usage


def call(name: str, **arguments: Any) -> ToolCall:
    call.counter += 1
    return ToolCall(id=f"c{call.counter}", name=name, arguments=arguments)


call.counter = 0


def says(text: str = "", *calls: ToolCall, stop: Optional[str] = None,
         tokens: Tuple[int, int] = (1000, 200)) -> Reply:
    return Reply(text=text, tool_calls=list(calls),
                 stop=stop or ("tool_use" if calls else "end"),
                 usage=Usage(*tokens), model="claude-opus-5-5", provider_type="anthropic")


@dataclass
class ScriptedConversation:
    script: List[Reply]
    log: List[Tuple[str, Any]]

    def ask(self) -> Reply:
        if not self.script:
            raise AssertionError("the model was asked more often than the script allows")
        reply = self.script.pop(0)
        self.log.append(("reply", reply))
        return reply

    def answer(self, results: Sequence[ToolResult]) -> None:
        self.log.append(("results", list(results)))

    def tell(self, text: str) -> None:
        self.log.append(("told", text))


@dataclass
class ScriptedProvider:
    script: List[Reply]
    log: List[Tuple[str, Any]] = field(default_factory=list)
    started: Dict[str, Any] = field(default_factory=dict)
    model: str = "claude-opus-5-5"
    provider_type: str = "anthropic"

    def conversation(self, *, system: Sequence[str], tools: Sequence[ToolSpec],
                     history: Sequence[Tuple[str, str]], prompt: str,
                     images: Sequence[Any] = ()) -> ScriptedConversation:
        self.started = {"system": list(system), "tools": [t.name for t in tools],
                        "history": list(history), "prompt": prompt, "images": list(images)}
        return ScriptedConversation(self.script, self.log)

    def results(self) -> List[ToolResult]:
        return [r for kind, batch in self.log if kind == "results" for r in batch]
