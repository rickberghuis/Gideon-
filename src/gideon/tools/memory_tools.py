"""Tools that let Gideon manage its own long-term memory (Tier 4).

remember/update are free (it's curating what it knows). forget deletes data, which is on the
never-without-asking list, so it is gated through the confirmation gate.
"""

from __future__ import annotations

from typing import Any

from ..memory import Memory
from .base import Tool


def build_tools(memory: Memory) -> list[Tool]:
    def remember(payload: dict[str, Any]) -> str:
        return memory.remember(payload.get("fact", ""), payload.get("slug"))

    def update(payload: dict[str, Any]) -> str:
        return memory.update(payload.get("slug", ""), payload.get("fact", ""))

    def forget(payload: dict[str, Any]) -> str:
        return memory.forget(payload.get("slug", ""))

    return [
        Tool(
            name="remember",
            description=(
                "Save a durable fact about the user for future conversations — a preference, "
                "an identity detail, or a decision. One clear statement per call. Use this when "
                "the user tells you something worth remembering long-term (not passing chatter)."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "fact": {"type": "string", "description": "The single fact to remember."},
                    "slug": {
                        "type": "string",
                        "description": "Optional short id; auto-generated if omitted.",
                    },
                },
                "required": ["fact"],
            },
            handler=remember,
        ),
        Tool(
            name="update_memory",
            description="Replace the text of an existing remembered fact, identified by its slug.",
            input_schema={
                "type": "object",
                "properties": {
                    "slug": {"type": "string"},
                    "fact": {"type": "string"},
                },
                "required": ["slug", "fact"],
            },
            handler=update,
        ),
        Tool(
            name="forget_memory",
            description="Delete a remembered fact by its slug. Use when a fact is wrong or stale.",
            input_schema={
                "type": "object",
                "properties": {"slug": {"type": "string"}},
                "required": ["slug"],
            },
            handler=forget,
            requires_confirmation=True,  # deleting data is gated
            action_summary=lambda p: f"Permanently forget memory '{p.get('slug', '?')}'",
        ),
    ]
