"""The provider seam.

Everything that talks to the model goes through here. Swapping providers, adding
retries, or changing how cost is measured happens in this one file — the agent never
touches the Anthropic SDK directly.

The seam streams text (so the terminal feels alive in Tier 1 and TTS can start early in
Tier 3) and surfaces tool-use requests so the agent can run tools and continue.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import anthropic

from .config import Config, require_env


class LLMError(RuntimeError):
    """Raised when the model is slow, unreachable, or rejects the request.

    The agent catches this and shows a clean message instead of a traceback."""


@dataclass
class ToolCall:
    """A request from the model to run one tool."""

    id: str
    name: str
    input: dict[str, Any]


@dataclass
class LLMResult:
    """The outcome of one model turn."""

    text: str = ""
    content: list[dict[str, Any]] = field(default_factory=list)  # raw assistant blocks
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str = ""
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def wants_tools(self) -> bool:
        return self.stop_reason == "tool_use" and bool(self.tool_calls)


# A callback that receives streamed text chunks as they arrive.
TextSink = Callable[[str], None]


class LLMClient:
    """Thin wrapper over the Anthropic Messages API. Streaming, tool-aware."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._client = anthropic.Anthropic(api_key=require_env("ANTHROPIC_API_KEY"))

    def stream(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        on_text: TextSink | None = None,
    ) -> LLMResult:
        """Send one turn; stream text via on_text; return the full result.

        `messages` is the running conversation in Anthropic format. `tools` is the
        registry's tool schema list (may be empty in Tier 1)."""
        cfg = self._config
        try:
            with self._client.messages.stream(
                model=cfg.model,
                max_tokens=cfg.max_tokens,
                system=system,
                messages=messages,
                tools=tools or [],
            ) as stream:
                for event in stream.text_stream:
                    if on_text and event:
                        on_text(event)
                final = stream.get_final_message()
        except anthropic.APIError as exc:
            raise LLMError(str(exc)) from exc
        except Exception as exc:  # network drop, timeout, etc.
            raise LLMError(f"Could not reach the model: {exc}") from exc

        return self._to_result(final)

    @staticmethod
    def _to_result(message: Any) -> LLMResult:
        result = LLMResult(stop_reason=message.stop_reason or "")
        raw_content: list[dict[str, Any]] = []
        text_parts: list[str] = []
        for block in message.content:
            if block.type == "text":
                text_parts.append(block.text)
                raw_content.append({"type": "text", "text": block.text})
            elif block.type == "tool_use":
                result.tool_calls.append(
                    ToolCall(id=block.id, name=block.name, input=dict(block.input))
                )
                raw_content.append(
                    {
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": dict(block.input),
                    }
                )
        result.text = "".join(text_parts)
        result.content = raw_content
        if message.usage:
            result.input_tokens = message.usage.input_tokens or 0
            result.output_tokens = message.usage.output_tokens or 0
        return result
