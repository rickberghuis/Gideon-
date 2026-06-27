"""Tier-by-tier tests that need no API key and no audio hardware.

Each test maps to a tier's verification step, using a scripted FakeLLM in place of the
provider seam so the agent loop, tools, memory, heartbeat, and rails are all exercised.
"""

from __future__ import annotations

import pytest

from gideon.agent import Agent
from gideon.config import load_config
from gideon.llm import LLMError, LLMResult, ToolCall
from gideon.memory import Memory
from gideon.tools.base import Registry, Tool
from gideon.tools import reminders as reminders_mod


class FakeLLM:
    """Returns scripted LLMResults; records the messages it was handed."""

    def __init__(self, results):
        self.results = list(results)
        self.calls = 0
        self.seen_messages = []

    def stream(self, system, messages, tools=None, on_text=None):
        self.seen_messages.append(list(messages))
        result = self.results[self.calls]
        self.calls += 1
        if on_text and result.text:
            on_text(result.text)
        return result


def cfg():
    return load_config()


# --- Tier 1: the brain remembers context within a session --------------------------------

def test_tier1_history_is_passed_back():
    fake = FakeLLM([
        LLMResult(text="Hi!", content=[{"type": "text", "text": "Hi!"}], stop_reason="end_turn"),
        LLMResult(text="Yes, milk.", content=[{"type": "text", "text": "Yes, milk."}], stop_reason="end_turn"),
    ])
    agent = Agent(config=cfg(), llm=fake)
    assert agent.send("hello") == "Hi!"
    agent.send("what did I say?")
    # second call must include the first exchange — that's memory within a session
    assert len(fake.seen_messages[1]) >= 3


def test_tier1_llm_error_is_graceful():
    class Boom:
        def stream(self, *a, **k):
            raise LLMError("network down")

    agent = Agent(config=cfg(), llm=Boom())
    reply = agent.send("hi")
    assert "couldn't reach" in reply.lower()


# --- Tier 2: tools run and feed results back; failures are handed back as data ------------

def test_tier2_tool_call_loop(tmp_path, monkeypatch):
    monkeypatch.setattr(reminders_mod, "REMINDERS_PATH", tmp_path / "reminders.json")
    registry = Registry()
    for t in reminders_mod.build_tools():
        registry.register(t)

    fake = FakeLLM([
        LLMResult(
            stop_reason="tool_use",
            content=[{"type": "tool_use", "id": "t1", "name": "add_reminder", "input": {"text": "buy milk"}}],
            tool_calls=[ToolCall(id="t1", name="add_reminder", input={"text": "buy milk"})],
        ),
        LLMResult(text="Added!", content=[{"type": "text", "text": "Added!"}], stop_reason="end_turn"),
    ])
    agent = Agent(config=cfg(), llm=fake, registry=registry)
    assert agent.send("remind me to buy milk") == "Added!"
    # the tool actually ran and persisted
    assert "buy milk" in reminders_mod.list_reminders({})


def test_tier2_tool_failure_is_returned_not_raised():
    def boom(_payload):
        raise ValueError("kaboom")

    registry = Registry()
    registry.register(Tool(name="explode", description="x", input_schema={"type": "object"}, handler=boom))
    fake = FakeLLM([
        LLMResult(
            stop_reason="tool_use",
            content=[{"type": "tool_use", "id": "t1", "name": "explode", "input": {}}],
            tool_calls=[ToolCall(id="t1", name="explode", input={})],
        ),
        LLMResult(text="That tool failed.", content=[{"type": "text", "text": "That tool failed."}], stop_reason="end_turn"),
    ])
    agent = Agent(config=cfg(), llm=fake, registry=registry)
    assert agent.send("go") == "That tool failed."
    # the tool_result handed to the model carried the error text
    tool_result_msg = fake.seen_messages[1][-1]["content"][0]
    assert tool_result_msg.get("is_error") is True
    assert "kaboom" in tool_result_msg["content"]


# --- Tier 4: memory survives + is editable -----------------------------------------------

def test_tier4_memory_roundtrip(tmp_path):
    mem = Memory(directory=tmp_path)
    mem.remember("prefers morning meetings")
    again = Memory(directory=tmp_path)  # simulate a restart
    assert "morning meetings" in again.render_for_prompt()
    slug = again.all()[0][0]
    again.forget(slug)
    assert again.render_for_prompt() == ""


# --- Tier 5: heartbeat scheduling, dedup, dismiss, quiet hours ----------------------------

def test_tier5_no_boot_stampede():
    from gideon.heartbeat import _due_now

    sched = {}
    # first sighting arms the timer instead of firing
    assert _due_now("c", 60, sched, now=1000.0) is False
    assert sched["c"] == 1060.0
    # not yet due
    assert _due_now("c", 60, sched, now=1059.0) is False
    # due after the interval
    assert _due_now("c", 60, sched, now=1060.0) is True


def test_tier5_inbox_dedup_and_dismiss(tmp_path):
    from gideon.heartbeat import Inbox, Notice

    inbox = Inbox(path=tmp_path / "inbox.json")
    assert inbox.add("c", Notice(text="due!", key="due:1")) is True
    assert inbox.add("c", Notice(text="due!", key="due:1")) is False  # deduped
    pending = inbox.pending()
    assert len(pending) == 1
    inbox.dismiss(pending[0]["id"])
    assert inbox.pending() == []


def test_tier5_quiet_hours():
    from gideon.heartbeat import in_quiet_hours
    from datetime import datetime

    c = load_config()
    # default window 22..8 wraps midnight
    assert in_quiet_hours(c, datetime(2026, 6, 27, 23, 0)) is True
    assert in_quiet_hours(c, datetime(2026, 6, 27, 12, 0)) is False


# --- Tier 6: the confirmation gate stops gated actions -----------------------------------

def test_tier6_gate_blocks_without_yes():
    registry = Registry()
    ran = {"sent": False}

    def fake_send(_p):
        ran["sent"] = True
        return "sent"

    registry.register(
        Tool(
            name="send_message",
            description="send",
            input_schema={"type": "object"},
            handler=fake_send,
            requires_confirmation=True,
            action_summary=lambda p: "send a message",
        )
    )
    fake = FakeLLM([
        LLMResult(
            stop_reason="tool_use",
            content=[{"type": "tool_use", "id": "t1", "name": "send_message", "input": {}}],
            tool_calls=[ToolCall(id="t1", name="send_message", input={})],
        ),
        LLMResult(text="Okay, I won't.", content=[{"type": "text", "text": "Okay, I won't."}], stop_reason="end_turn"),
    ])
    # confirmer that always says NO
    agent = Agent(config=cfg(), llm=fake, registry=registry, confirmer=lambda n, p, s: False)
    agent.send("send it")
    assert ran["sent"] is False
    result_block = fake.seen_messages[1][-1]["content"][0]
    assert "did not approve" in result_block["content"]


def test_tier6_kill_switch(tmp_path, monkeypatch):
    import gideon.safety as safety

    monkeypatch.setattr(safety, "_KILL_FILE", tmp_path / "KILLSWITCH")
    assert safety.kill_switch_engaged() is False
    safety.engage_kill_switch()
    assert safety.kill_switch_engaged() is True
    safety.release_kill_switch()
    assert safety.kill_switch_engaged() is False


# --- Web face: the browser confirmation gate (same core, different door) ------------------

def test_web_confirmer_timeout_denies():
    """The web gate falls back to the safe default (deny) if no one answers in time."""
    from gideon.web import WebConfirmer

    conf = WebConfirmer(timeout_seconds=0.2)
    assert conf("send_message", {"to": "Bob"}, "send a message") is False


def test_web_confirmer_allow_and_deny():
    import threading
    from gideon.web import WebConfirmer

    for verdict in (True, False):
        conf = WebConfirmer(timeout_seconds=5)
        result = {}

        def ask():
            result["r"] = conf("send_message", {}, "send a message")

        t = threading.Thread(target=ask)
        t.start()
        # wait for the pending action to surface, then answer it
        for _ in range(50):
            snap = conf.snapshot()
            if snap:
                break
            threading.Event().wait(0.02)
        assert snap is not None
        conf.resolve(snap["id"], verdict)
        t.join(timeout=2)
        assert result["r"] is verdict
