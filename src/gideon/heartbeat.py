"""The heartbeat — proactive, quiet by default (Tier 5).

A background loop, separate from the conversation, that wakes on an interval, runs scheduled
checks, and routes anything noteworthy into one place: the inbox. The conversation shows held
inbox items on return, so nothing is delivered-once-and-lost.

Design notes that keep it from becoming annoying or fragile:
- Quiet by default: most checks surface nothing; only the noteworthy reaches the inbox.
- Catch-up-on-return: notices persist in state/inbox.json until dismissed.
- Quiet hours: only "critical" severity surfaces live at night; others wait (they're held
  anyway, since the inbox is pull-based).
- Survive restarts: next-due per check persists in state/schedule.json — no boot stampede.
- No overlapping runs: the loop is sequential, so a slow check can't stack on itself.
- Kill switch: when engaged, the loop idles without running checks.
- Machine-agnostic: nothing here assumes which host it runs on — relocate, don't rewrite.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from .config import (
    INBOX_PATH,
    SCHEDULE_PATH,
    STATE_DIR,
    Config,
    REMINDERS_PATH,
    load_config,
)
from .safety import kill_switch_engaged
from .storage import read_json, write_json


# --- a surfaced item ---------------------------------------------------------------------

@dataclass
class Notice:
    text: str
    severity: str = "log"   # "log" | "interrupt" | "critical"
    key: str = ""           # dedup key; an undismissed notice with the same key isn't re-added


# --- the inbox (held, dismissible notices) -----------------------------------------------

class Inbox:
    def __init__(self, path=INBOX_PATH) -> None:
        self.path = path

    def _all(self) -> list[dict[str, Any]]:
        return read_json(self.path, [])

    def add(self, check: str, notice: Notice) -> bool:
        items = self._all()
        if notice.key and any(
            i for i in items if not i["dismissed"] and i.get("key") == notice.key
        ):
            return False  # already surfaced and not yet dealt with — don't pile up
        items.append(
            {
                "id": uuid.uuid4().hex[:8],
                "check": check,
                "text": notice.text,
                "severity": notice.severity,
                "key": notice.key,
                "created": datetime.now(timezone.utc).isoformat(),
                "dismissed": False,
            }
        )
        write_json(self.path, items)
        return True

    def pending(self) -> list[dict[str, Any]]:
        return [i for i in self._all() if not i["dismissed"]]

    def dismiss(self, notice_id: str) -> str:
        items = self._all()
        for i in items:
            if i["id"] == notice_id:
                i["dismissed"] = True
                write_json(self.path, items)
                return f"Dismissed {notice_id}."
        return f"No pending notice {notice_id}."

    def render_pending(self) -> str:
        items = self.pending()
        if not items:
            return ""
        lines = ["📬 While you were away:"]
        for i in items:
            flag = {"critical": "‼️", "interrupt": "❗"}.get(i["severity"], "•")
            lines.append(f"  {flag} [{i['id']}] {i['text']}")
        lines.append("  (say 'dismiss <id>' to clear one)")
        return "\n".join(lines)


# --- checks ------------------------------------------------------------------------------
# Each check looks at something and returns notices worth surfacing (often none).

CheckFn = Callable[[Config], list[Notice]]


def check_due_reminders(config: Config) -> list[Notice]:
    items = read_json(REMINDERS_PATH, [])
    now = datetime.now(timezone.utc)
    out = []
    for r in items:
        if r.get("done") or not r.get("due"):
            continue
        try:
            due = datetime.fromisoformat(r["due"])
            if due.tzinfo is None:
                due = due.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if due <= now:
            out.append(
                Notice(text=f"Reminder due: {r['text']}", severity="interrupt", key=f"due:{r['id']}")
            )
    return out


def check_heartbeat_demo(config: Config) -> list[Notice]:
    """Verification hook for Tier 5: surfaces a note when state/trigger.txt exists."""
    trigger = STATE_DIR / "trigger.txt"
    if trigger.exists():
        return [Notice(text="Demo check fired (trigger.txt present).", severity="log", key="demo")]
    return []


CHECKS: dict[str, CheckFn] = {
    "due_reminders": check_due_reminders,
    "heartbeat_demo": check_heartbeat_demo,
}


# --- quiet hours -------------------------------------------------------------------------

def in_quiet_hours(config: Config, now: datetime | None = None) -> bool:
    hb = config.heartbeat
    start = int(hb.get("quiet_hours_start", 22))
    end = int(hb.get("quiet_hours_end", 8))
    hour = (now or datetime.now()).hour
    if start == end:
        return False
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end  # window wraps midnight


# --- the schedule (durable next-due) -----------------------------------------------------

def _due_now(name: str, every: int, schedule: dict[str, float], now: float) -> bool:
    next_due = schedule.get(name)
    if next_due is None:
        # First time we've seen this check: arm it for one interval out — no boot stampede.
        schedule[name] = now + every
        return False
    return now >= next_due


# --- the loop ----------------------------------------------------------------------------

def run_once(config: Config, inbox: Inbox, schedule: dict[str, float], now: float) -> None:
    """Run any checks that are due. Sequential, so runs never overlap."""
    for spec in config.heartbeat.get("checks", []):
        name = spec.get("name")
        fn = CHECKS.get(name)
        if fn is None:
            continue
        every = int(spec.get("every_seconds", 60))
        if not _due_now(name, every, schedule, now):
            continue
        schedule[name] = now + every  # arm next run before running (skip-overlap semantics)
        severity_cap = spec.get("severity", "log")
        try:
            notices = fn(config)
        except Exception:
            continue  # a flaky check must not kill the loop
        for notice in notices:
            # A check can't be louder than its configured severity cap.
            if severity_cap != "critical" and notice.severity == "critical":
                notice.severity = severity_cap
            # Respect quiet hours: only critical surfaces live at night. Others are held
            # anyway (inbox is pull-based), so we simply add them and let the user catch up.
            if notice.severity in {"interrupt", "critical"} and in_quiet_hours(config) and notice.severity != "critical":
                notice.severity = "log"
            inbox.add(name, notice)


def _tick(config: Config, inbox: Inbox, schedule: dict[str, float]) -> None:
    """One beat: run due checks if enabled and not paused, then persist the schedule."""
    if config.heartbeat.get("enabled", True) and not kill_switch_engaged(config):
        run_once(config, inbox, schedule, time.time())
        write_json(SCHEDULE_PATH, schedule)  # persist next-due across restarts


def heartbeat_loop() -> None:
    """Entry point for `gideon --heartbeat`. Runs until interrupted."""
    inbox = Inbox()
    schedule: dict[str, float] = read_json(SCHEDULE_PATH, {})
    print("💓 Heartbeat running. Ctrl-C to stop.")
    try:
        while True:
            config = load_config()  # reload each tick: config edits take effect live
            _tick(config, inbox, schedule)
            time.sleep(int(config.heartbeat.get("tick_seconds", 30)))
    except KeyboardInterrupt:
        print("\n💤 Heartbeat stopped.")


def run_background(stop_event) -> None:
    """Same loop, driven by a threading.Event — used by the web server so one process
    gives you both the chat face and a beating heartbeat. Relocatable as ever."""
    inbox = Inbox()
    schedule: dict[str, float] = read_json(SCHEDULE_PATH, {})
    while not stop_event.is_set():
        config = load_config()
        _tick(config, inbox, schedule)
        stop_event.wait(int(config.heartbeat.get("tick_seconds", 30)))
