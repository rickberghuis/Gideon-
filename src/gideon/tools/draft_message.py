"""Draft messages — capability #3.

Drafting is free: it just composes text for the user's review. *Sending* is a separate,
gated tool (sending a message is on the "never without asking" list), so it carries
requires_confirmation=True and a clear action summary for the confirmation gate (Tier 6).

The actual send here is a safe placeholder that writes to an outbox file — swap in a real
email/chat provider behind this same handler later.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..config import STATE_DIR
from ..storage import read_json, write_json
from .base import Tool

_OUTBOX = STATE_DIR / "outbox.json"


def draft_message(payload: dict[str, Any]) -> str:
    to = (payload.get("to") or "").strip()
    subject = (payload.get("subject") or "").strip()
    body = (payload.get("body") or "").strip()
    if not body:
        return "I need at least the message body to draft something."
    lines = []
    if to:
        lines.append(f"To: {to}")
    if subject:
        lines.append(f"Subject: {subject}")
    lines.append("")
    lines.append(body)
    return "Here's a draft for your review:\n\n" + "\n".join(lines)


def send_message(payload: dict[str, Any]) -> str:
    to = (payload.get("to") or "").strip()
    body = (payload.get("body") or "").strip()
    if not to or not body:
        return "Sending needs both a recipient and a body."
    outbox = read_json(_OUTBOX, [])
    outbox.append(
        {
            "to": to,
            "subject": (payload.get("subject") or "").strip(),
            "body": body,
            "sent_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    write_json(_OUTBOX, outbox)
    return f"Sent to {to}. (Placeholder send — wire a real provider to actually deliver.)"


def _send_summary(payload: dict[str, Any]) -> str:
    to = (payload.get("to") or "?").strip()
    subject = (payload.get("subject") or "").strip()
    suffix = f" about '{subject}'" if subject else ""
    return f"Send a message to {to}{suffix}"


def build_tools() -> list[Tool]:
    return [
        Tool(
            name="draft_message",
            description=(
                "Compose a draft email or message for the user to review. Use this when the "
                "user asks you to write a message. This does NOT send anything."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "Recipient (optional for a draft)."},
                    "subject": {"type": "string"},
                    "body": {"type": "string", "description": "The message body."},
                },
                "required": ["body"],
            },
            handler=draft_message,
        ),
        Tool(
            name="send_message",
            description=(
                "Actually send a message to a recipient. Only use after the user has reviewed a "
                "draft and clearly asked you to send it. This is a consequential action."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "to": {"type": "string"},
                    "subject": {"type": "string"},
                    "body": {"type": "string"},
                },
                "required": ["to", "body"],
            },
            handler=send_message,
            requires_confirmation=True,  # gated: sending is on the never-without-asking list
            action_summary=_send_summary,
        ),
    ]
