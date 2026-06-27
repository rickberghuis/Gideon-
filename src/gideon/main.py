"""Composition root + entrypoints.

  gideon                 text conversation (the always-available debugging path)
  gideon --voice         push-to-talk voice (Tier 3)
  gideon --heartbeat     run the proactive background loop (Tier 5)
  gideon --kill          engage the kill switch (pause all proactive behavior)
  gideon --unkill        release the kill switch

Every mode drives the SAME agent core. Voice and the heartbeat are adapters on its edges.
"""

from __future__ import annotations

import argparse
import sys
import threading
from queue import Queue

from .agent import NAME, Agent
from .audit import Audit
from .config import ensure_state_dirs, load_config
from .heartbeat import Inbox, heartbeat_loop
from .memory import Memory
from .safety import engage_kill_switch, release_kill_switch, terminal_confirmer
from .tools.registry import build_registry


def build_agent(on_text=None) -> tuple[Agent, Audit, Memory, Inbox]:
    """Assemble the full assistant from its independently-built parts."""
    ensure_state_dirs()
    config = load_config()
    audit = Audit(config)
    memory = Memory()
    registry = build_registry(memory)
    agent = Agent(
        config=config,
        registry=registry,
        memory=memory,
        audit=audit,
        confirmer=terminal_confirmer,
        on_text=on_text,
    )
    return agent, audit, memory, Inbox()


def _greeting(memory: Memory) -> str:
    known = memory.render_for_prompt()
    if known:
        return f"{NAME} here. I remember a few things about you. What's up?"
    return f"{NAME} here. We haven't talked before — tell me anything you want me to remember."


def _handle_command(text: str, inbox: Inbox, audit: Audit) -> bool:
    """Handle local REPL commands. Returns True if the input was a command."""
    low = text.strip().lower()
    if low in {"exit", "quit", ":q"}:
        raise SystemExit(0)
    if low in {"/kill", "kill switch on"}:
        print(engage_kill_switch())
        return True
    if low in {"/unkill", "kill switch off"}:
        print(release_kill_switch())
        return True
    if low == "/cost":
        print(f"Session cost so far: ${audit.session_cost_usd:.4f}")
        return True
    if low.startswith("dismiss "):
        print(inbox.dismiss(text.split(maxsplit=1)[1].strip()))
        return True
    return False


# --- text mode ---------------------------------------------------------------------------

class _StreamPrinter:
    def __init__(self) -> None:
        self.any = False

    def __call__(self, chunk: str) -> None:
        self.any = True
        sys.stdout.write(chunk)
        sys.stdout.flush()


def run_text() -> None:
    printer = _StreamPrinter()
    agent, audit, memory, inbox = build_agent(on_text=printer)
    print(_greeting(memory))
    pending = inbox.render_pending()
    if pending:
        print("\n" + pending)
    while True:
        try:
            user = input("\nyou> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nbye 👋")
            return
        if not user:
            continue
        try:
            if _handle_command(user, inbox, audit):
                continue
        except SystemExit:
            print("bye 👋")
            return
        printer.any = False
        print(f"{NAME.lower()}> ", end="", flush=True)
        reply = agent.send(user)
        if not printer.any and reply:
            print(reply, end="")
        print()
        new_pending = inbox.render_pending()
        if new_pending:
            print("\n" + new_pending)


# --- voice mode (Tier 3) -----------------------------------------------------------------

def run_voice() -> None:
    from .voice.capture import record_while_held
    from .voice.stt import Transcriber
    from .voice.tts import Speaker

    config = load_config()
    transcriber = Transcriber(config)
    speaker = Speaker(config)
    key = config.voice.get("push_to_talk_key", "space")

    # Early speech: a worker thread speaks complete sentences as they stream in.
    speak_q: "Queue[str | None]" = Queue()

    def speak_worker():
        while True:
            sentence = speak_q.get()
            if sentence is None:
                return
            speaker.speak(sentence)

    buffer = {"text": ""}

    def on_text(chunk: str):
        sys.stdout.write(chunk)
        sys.stdout.flush()
        buffer["text"] += chunk
        # flush complete sentences to the speaker as they form
        while True:
            import re

            m = re.match(r"(.+?[.!?])(\s|$)", buffer["text"])
            if not m:
                break
            speak_q.put(m.group(1).strip())
            buffer["text"] = buffer["text"][m.end():]

    agent, audit, memory, inbox = build_agent(on_text=on_text)
    print(_greeting(memory))
    pending = inbox.render_pending()
    if pending:
        print("\n" + pending)
    print(f"\nVoice mode. Hold [{key}] to talk. Ctrl-C to quit. (Typed mode still available via `gideon`.)")

    try:
        while True:
            pcm, rate = record_while_held(key)
            if not pcm:
                continue
            print("…transcribing", flush=True)
            heard = transcriber.transcribe(pcm, rate)
            if not heard:
                print("(didn't catch that)")
                continue
            print(f"\nyou said> {heard}")  # show transcript so mishears are visible
            print(f"{NAME.lower()}> ", end="", flush=True)

            worker = threading.Thread(target=speak_worker, daemon=True)
            worker.start()
            buffer["text"] = ""
            reply = agent.send(heard)
            if buffer["text"].strip():
                speak_q.put(buffer["text"].strip())
            speak_q.put(None)
            worker.join()
            print()
            new_pending = inbox.render_pending()
            if new_pending:
                print("\n" + new_pending)
    except KeyboardInterrupt:
        speaker.interrupt()
        print("\nbye 👋")


# --- entrypoint --------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(prog="gideon", description="Gideon — voice-first assistant")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--voice", action="store_true", help="push-to-talk voice mode")
    group.add_argument("--heartbeat", action="store_true", help="run the proactive background loop")
    group.add_argument("--kill", action="store_true", help="engage kill switch (pause proactive)")
    group.add_argument("--unkill", action="store_true", help="release kill switch")
    args = parser.parse_args()

    if args.kill:
        print(engage_kill_switch())
    elif args.unkill:
        print(release_kill_switch())
    elif args.heartbeat:
        ensure_state_dirs()
        heartbeat_loop()
    elif args.voice:
        run_voice()
    else:
        run_text()


if __name__ == "__main__":
    main()
