"""Configuration + paths — the single place that reads config.toml and the environment.

Nothing else in the harness should read config.toml or os.environ directly; go through
here so tunables stay in one spot (Tier 6: config over hardcoding).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover - 3.9/3.10 fallback
    import tomli as tomllib
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

# Project root = two levels up from this file (src/gideon/config.py -> project root).
ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config.toml"
STATE_DIR = ROOT / "state"
MEMORY_DIR = STATE_DIR / "memory"
INBOX_PATH = STATE_DIR / "inbox.json"
SCHEDULE_PATH = STATE_DIR / "schedule.json"
AUDIT_PATH = STATE_DIR / "audit.jsonl"
REMINDERS_PATH = STATE_DIR / "reminders.json"
NOTES_DIR = STATE_DIR / "notes"

# Load .env once at import so ANTHROPIC_API_KEY etc. are available.
load_dotenv(ROOT / ".env")


@dataclass(frozen=True)
class Config:
    """Parsed, typed view of config.toml. Reloaded each time load_config() is called
    so the heartbeat picks up edits (Tier 6: change a threshold, no code edit)."""

    raw: dict[str, Any] = field(default_factory=dict)

    # --- model ---
    @property
    def model(self) -> str:
        return self.raw.get("model", {}).get("name", "claude-sonnet-4-6")

    @property
    def max_tokens(self) -> int:
        return int(self.raw.get("model", {}).get("max_tokens", 1024))

    @property
    def input_price_per_mtok(self) -> float:
        return float(self.raw.get("model", {}).get("input_price_per_mtok", 0.0))

    @property
    def output_price_per_mtok(self) -> float:
        return float(self.raw.get("model", {}).get("output_price_per_mtok", 0.0))

    # --- voice ---
    @property
    def voice(self) -> dict[str, Any]:
        return self.raw.get("voice", {})

    # --- safety ---
    @property
    def gated_actions(self) -> list[str]:
        return list(self.raw.get("safety", {}).get("gated_actions", []))

    @property
    def proactive_paused(self) -> bool:
        return bool(self.raw.get("safety", {}).get("proactive_paused", False))

    # --- heartbeat ---
    @property
    def heartbeat(self) -> dict[str, Any]:
        return self.raw.get("heartbeat", {})


def load_config() -> Config:
    """Read config.toml fresh. Safe to call often; the heartbeat calls it each tick."""
    if CONFIG_PATH.exists():
        with CONFIG_PATH.open("rb") as fh:
            data = tomllib.load(fh)
    else:
        data = {}
    return Config(raw=data)


def require_env(name: str) -> str:
    """Fetch a required secret or raise a clear, actionable error."""
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(
            f"Missing {name}. Copy .env.example to .env and fill it in "
            f"(see AGENT.md / README)."
        )
    return value


def ensure_state_dirs() -> None:
    """Create the git-ignored durable-state directories if missing."""
    for path in (STATE_DIR, MEMORY_DIR, NOTES_DIR):
        path.mkdir(parents=True, exist_ok=True)
