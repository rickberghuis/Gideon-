"""Reminders & tasks — capability #1.

A reminder is one durable record: text, optional due time (ISO 8601), and done flag.
Stored in state/reminders.json so it survives restarts and the heartbeat can read it
(Tier 5 surfaces due reminders).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from ..config import REMINDERS_PATH
from ..storage import read_json, write_json
from .base import Tool


def _load() -> list[dict[str, Any]]:
    return read_json(REMINDERS_PATH, [])


def _save(items: list[dict[str, Any]]) -> None:
    write_json(REMINDERS_PATH, items)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def add_reminder(payload: dict[str, Any]) -> str:
    text = (payload.get("text") or "").strip()
    if not text:
        return "I need the reminder text."
    due = (payload.get("due") or "").strip() or None
    if due:
        try:
            datetime.fromisoformat(due)
        except ValueError:
            return f"'{due}' isn't a valid ISO 8601 time (e.g. 2026-06-28T09:00:00)."
    items = _load()
    items.append(
        {
            "id": uuid.uuid4().hex[:8],
            "text": text,
            "due": due,
            "done": False,
            "created": _now().isoformat(),
        }
    )
    _save(items)
    when = f" (due {due})" if due else ""
    return f"Added reminder: {text}{when}"


def list_reminders(payload: dict[str, Any]) -> str:
    include_done = bool(payload.get("include_done", False))
    items = [i for i in _load() if include_done or not i.get("done")]
    if not items:
        return "Nothing on your list."
    lines = []
    for i in items:
        mark = "x" if i.get("done") else " "
        due = f" — due {i['due']}" if i.get("due") else ""
        lines.append(f"[{mark}] {i['id']}: {i['text']}{due}")
    return "\n".join(lines)


def complete_reminder(payload: dict[str, Any]) -> str:
    rid = (payload.get("id") or "").strip()
    items = _load()
    for i in items:
        if i["id"] == rid:
            i["done"] = True
            _save(items)
            return f"Marked done: {i['text']}"
    return f"No reminder with id {rid}."


def build_tools() -> list[Tool]:
    return [
        Tool(
            name="add_reminder",
            description=(
                "Add a reminder or task to the user's list. Use this whenever the user wants "
                "to be reminded of something or asks you to note a to-do. Optionally include a "
                "due time in ISO 8601 (e.g. 2026-06-28T09:00:00)."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "What to be reminded of."},
                    "due": {
                        "type": "string",
                        "description": "Optional ISO 8601 due time.",
                    },
                },
                "required": ["text"],
            },
            handler=add_reminder,
        ),
        Tool(
            name="list_reminders",
            description=(
                "List the user's current reminders/tasks. Use this when the user asks what's "
                "on their list, what they need to do, or what's due."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "include_done": {
                        "type": "boolean",
                        "description": "Include completed items too. Defaults to false.",
                    }
                },
            },
            handler=list_reminders,
        ),
        Tool(
            name="complete_reminder",
            description="Mark a reminder done by its id. Use after the user finishes a task.",
            input_schema={
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "The reminder id to complete."}
                },
                "required": ["id"],
            },
            handler=complete_reminder,
        ),
    ]
