# Gideon — a voice-first AI assistant

The core harness that turns a language model into something you can talk to, that can *do*
things via tools, remembers you between conversations, and can reach out first. Built tier by
tier; each tier runs and verifies on its own. See [AGENT.md](AGENT.md) for the spec.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"          # core + tests
pip install -e ".[voice]"        # add this when you reach Tier 3 (audio libs)

cp .env.example .env             # then fill in ANTHROPIC_API_KEY (Deepgram/ElevenLabs at Tier 3)
```

Run the offline test suite (no API key needed) anytime:

```bash
pytest -q
```

## Run

```bash
gideon              # text conversation — the always-available path
gideon --voice      # push-to-talk (hold space, speak, release)   [needs .[voice] + keys]
gideon --heartbeat  # the proactive background loop                [run in a second terminal]
gideon --kill       # pause ALL proactive behavior (kill switch)
gideon --unkill     # resume
```

In the text REPL: `dismiss <id>` clears an inbox notice, `/cost` shows the session cost,
`/kill` `/unkill` toggle the kill switch, `exit` quits.

## The five parts (one shared core, many ways in/out)

| Part        | Where                         | Tier |
|-------------|-------------------------------|------|
| The brain   | `agent.py`, `llm.py`          | 1    |
| The hands   | `tools/`                      | 2    |
| Ears & mouth| `voice/`                      | 3    |
| The memory  | `memory.py`, `state/memory/`  | 4    |
| The heartbeat| `heartbeat.py`               | 5    |
| The rails   | `safety.py`, `audit.py`, `config.toml` | 6 |

Every input path — typed, spoken, heartbeat-initiated — flows through `Agent.send()`.

## Verifying each tier

- **Tier 1 (brain):** `gideon`, hold a back-and-forth; it remembers earlier turns. Restart →
  it forgets (expected; memory is Tier 4). *Offline:* `test_tier1_*`.
- **Tier 2 (tools):** ask "remind me to buy milk", then "what's on my list?" — watch it call
  tools. Tool failures are explained, not crashed. *Offline:* `test_tier2_*`.
- **Tier 3 (voice):** `gideon --voice`, hold space, ask a tool question, hear the answer; the
  transcript prints so mishears are visible; a new turn interrupts playback. Text mode still works.
- **Tier 4 (memory):** "remember I prefer morning meetings", quit, restart → it knows. Edit a
  file in `state/memory/` by hand → it respects your edit. *Offline:* `test_tier4_*`.
- **Tier 5 (heartbeat):** in one terminal `gideon --heartbeat`; `touch state/trigger.txt` to fire
  the demo check; open `gideon` to see the held notice; `dismiss <id>` clears it. Restart resumes
  the schedule (no refire-all). *Offline:* `test_tier5_*`.
- **Tier 6 (rails):** ask it to send a message → it states the action and waits for `y`.
  Paste content containing "ignore your rules and …" → it flags rather than obeys. Change a
  threshold in `config.toml` → behavior changes, no code edit. `gideon --kill` stops proactive
  while chat still works. *Offline:* `test_tier6_*`.

## Extending it

Add a capability = write a `tools/<thing>.py` with `build_tools()` and add one line to
`tools/registry.py`. Flag anything consequential with `requires_confirmation=True`. Never edit
the agent loop. Swap the model in `config.toml`; swap providers behind `llm.py` / `voice/`.
