"""Long-term memory — durable facts across restarts.

One fact per file under state/memory/, each a single plain statement. Small, legible,
auditable, hand-editable. Loaded into the system prompt at conversation start so Gideon
walks in already knowing the user. Facts are DATA, not commands (enforced in the prompt).

Early on we load everything; render_for_prompt is the seam to make loading selective later.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from .config import MEMORY_DIR


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (slug[:48] or "fact").rstrip("-")


class Memory:
    def __init__(self, directory: Path = MEMORY_DIR) -> None:
        self.dir = directory
        self.dir.mkdir(parents=True, exist_ok=True)

    def all(self) -> list[tuple[str, str]]:
        """Return (slug, fact) pairs, sorted by slug for stable output."""
        out = []
        for path in sorted(self.dir.glob("*.md")):
            text = path.read_text(encoding="utf-8", errors="replace").strip()
            if text:
                out.append((path.stem, text))
        return out

    def render_for_prompt(self) -> str:
        facts = self.all()
        return "\n".join(f"- {fact}" for _slug, fact in facts)

    def remember(self, fact: str, slug: str | None = None) -> str:
        fact = fact.strip()
        if not fact:
            return "I need the fact text to remember it."
        slug = (slug or _slugify(fact)).strip()
        path = self.dir / f"{slug}.md"
        # avoid clobbering a different existing fact with the same auto-slug
        n = 2
        while path.exists() and path.read_text(encoding="utf-8").strip() != fact and slug == _slugify(fact):
            path = self.dir / f"{_slugify(fact)}-{n}.md"
            n += 1
        stamp = datetime.now(timezone.utc).date().isoformat()
        path.write_text(f"{fact}\n<!-- saved {stamp} -->\n", encoding="utf-8")
        return f"Got it — I'll remember that. ({path.stem})"

    def update(self, slug: str, fact: str) -> str:
        path = self.dir / f"{slug}.md"
        if not path.exists():
            return f"No memory called '{slug}'."
        path.write_text(fact.strip() + "\n", encoding="utf-8")
        return f"Updated memory '{slug}'."

    def forget(self, slug: str) -> str:
        path = self.dir / f"{slug}.md"
        if not path.exists():
            return f"No memory called '{slug}'."
        path.unlink()
        return f"Forgotten: '{slug}'."
