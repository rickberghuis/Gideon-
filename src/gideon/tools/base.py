"""The Tool abstraction and the registry.

A tool is a named capability: a clear name, a description written for the *model* to read
("use this to look up the weather for a city" beats "weather()"), a typed input schema, and
a handler. Tools that send, spend, delete, or change a setting set requires_confirmation so
the agent's gate (Tier 6) stops them until the user says yes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

Handler = Callable[[dict[str, Any]], str]
ActionSummary = Callable[[dict[str, Any]], str]


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Handler
    # True for anything consequential (send/spend/delete/change). Gated in Tier 6.
    requires_confirmation: bool = False
    # Builds the one-line "here's what I'm about to do" text shown at the gate.
    action_summary: ActionSummary | None = None

    def run(self, payload: dict[str, Any]) -> str:
        """Run the tool. Always return a string for the model to read."""
        return self.handler(payload or {})

    def describe_action(self, payload: dict[str, Any]) -> str:
        if self.action_summary:
            return self.action_summary(payload or {})
        return f"{self.name}({payload})"

    def schema(self) -> dict[str, Any]:
        """Anthropic tool-definition shape handed to the model each turn."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


class Registry:
    """Holds the tools and exposes them to the model. The thing you extend forever."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Duplicate tool name: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def schemas(self) -> list[dict[str, Any]]:
        return [tool.schema() for tool in self._tools.values()]

    def names(self) -> list[str]:
        return list(self._tools)
