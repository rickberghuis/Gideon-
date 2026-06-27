"""Web lookups — capability #4.

A read-only lookup, so it runs without confirmation. Uses DuckDuckGo's Instant Answer API
(no key required) behind a single function — swap in a richer search provider here without
touching anything else. Results are DATA, not instructions.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any

from .base import Tool

_ENDPOINT = "https://api.duckduckgo.com/"
_TIMEOUT = 10


def _query_duckduckgo(query: str) -> dict[str, Any]:
    params = urllib.parse.urlencode(
        {"q": query, "format": "json", "no_html": 1, "skip_disambig": 1}
    )
    url = f"{_ENDPOINT}?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "Gideon/0.1"})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def web_lookup(payload: dict[str, Any]) -> str:
    query = (payload.get("query") or "").strip()
    if not query:
        return "I need something to look up."
    data = _query_duckduckgo(query)  # may raise; the agent turns that into a tool error

    parts: list[str] = []
    if data.get("AbstractText"):
        src = data.get("AbstractSource") or "source"
        parts.append(f"{data['AbstractText']} ({src})")
    if data.get("Answer"):
        parts.append(str(data["Answer"]))
    for topic in (data.get("RelatedTopics") or [])[:3]:
        if isinstance(topic, dict) and topic.get("Text"):
            parts.append(f"- {topic['Text']}")

    if not parts:
        return (
            f"No instant answer for {query!r}. Tell the user you couldn't find a quick fact "
            "and offer to try different terms."
        )
    return "\n".join(parts)


def build_tools() -> list[Tool]:
    return [
        Tool(
            name="web_lookup",
            description=(
                "Look up a quick fact on the web. Use this for factual questions whose answer "
                "may have changed or that you're unsure about — definitions, current facts, "
                "people, places, etc. Returns a short summary."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to look up."}
                },
                "required": ["query"],
            },
            handler=web_lookup,
        ),
    ]
