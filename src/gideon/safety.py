"""The rails (Tier 6): confirmation gate, kill switch.

The gate sits between the model choosing a consequential tool and the tool running, so it
covers typed, spoken, and heartbeat-initiated actions alike. Approval is per-action and
never generalizes.
"""

from __future__ import annotations

from typing import Any

from .config import STATE_DIR

# Sentinel file = one obvious kill switch for all proactive behavior.
_KILL_FILE = STATE_DIR / "KILLSWITCH"


# --- confirmation gate -------------------------------------------------------------------

def terminal_confirmer(name: str, payload: dict[str, Any], summary: str) -> bool:
    """Interactive gate for text/voice mode. States plainly what's about to happen and
    waits for an explicit yes. Anything other than y/yes is a no."""
    print(f"\n⚠️  Gideon wants to: {summary}")
    print(f"   tool: {name}  args: {payload}")
    try:
        answer = input("   Allow this? [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    return answer in {"y", "yes"}


def background_confirmer(name: str, payload: dict[str, Any], summary: str) -> bool:
    """Gate for the heartbeat / unattended context. Never blocks waiting on a human:
    it times out immediately to the safe default — do nothing — so the loop keeps running.
    A real deployment could escalate to a notification first; the safe default stays 'no'."""
    return False


# --- kill switch -------------------------------------------------------------------------

def kill_switch_engaged(config: Any | None = None) -> bool:
    """True if proactive behavior should be paused — via the sentinel file or config flag."""
    if _KILL_FILE.exists():
        return True
    if config is not None:
        return bool(getattr(config, "proactive_paused", False))
    return False


def engage_kill_switch() -> str:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    _KILL_FILE.write_text("proactive behavior paused\n", encoding="utf-8")
    return "Kill switch ON — all proactive behavior paused. You can still talk to me."


def release_kill_switch() -> str:
    if _KILL_FILE.exists():
        _KILL_FILE.unlink()
    return "Kill switch OFF — proactive behavior resumes."
