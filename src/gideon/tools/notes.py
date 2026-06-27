"""Notes Q&A — capability #2.

Notes are plain text/markdown files under state/notes/. The tool finds relevant notes by
keyword and returns their content so the model can answer over them. Content returned here
is DATA, not instructions (the system prompt enforces that posture).
"""

from __future__ import annotations

from typing import Any

from ..config import NOTES_DIR
from .base import Tool

_MAX_CHARS = 4000


def _iter_notes():
    if not NOTES_DIR.exists():
        return []
    return sorted(p for p in NOTES_DIR.glob("**/*") if p.suffix in {".txt", ".md"})


def search_notes(payload: dict[str, Any]) -> str:
    query = (payload.get("query") or "").strip().lower()
    if not query:
        return "I need something to search for."
    terms = [t for t in query.split() if t]
    hits: list[tuple[int, str, str]] = []
    for path in _iter_notes():
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        score = sum(text.lower().count(t) for t in terms)
        if score:
            hits.append((score, path.name, text))
    if not hits:
        return f"No notes mention {query!r}. (Notes live in {NOTES_DIR}.)"
    hits.sort(reverse=True)
    out, used = [], 0
    for _score, name, text in hits[:5]:
        snippet = text[:_MAX_CHARS]
        if used + len(snippet) > _MAX_CHARS * 2:
            break
        used += len(snippet)
        out.append(f"--- {name} ---\n{snippet}")
    return "\n\n".join(out)


def add_note(payload: dict[str, Any]) -> str:
    title = (payload.get("title") or "").strip()
    body = (payload.get("body") or "").strip()
    if not title or not body:
        return "I need both a title and a body for the note."
    safe = "".join(c if c.isalnum() or c in "-_ " else "_" for c in title).strip().replace(" ", "_")
    path = NOTES_DIR / f"{safe or 'note'}.md"
    NOTES_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# {title}\n\n{body}\n", encoding="utf-8")
    return f"Saved note '{title}'."


def build_tools() -> list[Tool]:
    return [
        Tool(
            name="search_notes",
            description=(
                "Search the user's personal notes by keyword and return the matching note "
                "text. Use this whenever the user asks a question that might be answered by "
                "their own notes, documents, or things they've saved."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Keywords to search for."}
                },
                "required": ["query"],
            },
            handler=search_notes,
        ),
        Tool(
            name="add_note",
            description="Save a new personal note with a title and body for later retrieval.",
            input_schema={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "body": {"type": "string"},
                },
                "required": ["title", "body"],
            },
            handler=add_note,
        ),
    ]
