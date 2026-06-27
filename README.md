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
gideon --web        # browser chat UI at http://127.0.0.1:8000  (--port to change)
gideon --voice      # push-to-talk (hold space, speak, release)   [needs .[voice] + keys]
gideon --voice-check# synthesize+play one line to test the ElevenLabs key/voice
gideon --heartbeat  # the proactive background loop                [run in a second terminal]
gideon --kill       # pause ALL proactive behavior (kill switch)
gideon --unkill     # resume
```

### The web face (`gideon --web`)

A localhost-only chat UI — the same agent core, a different door in. It shows replies, the
heartbeat inbox (with dismiss buttons), the running cost, and a heartbeat on/off toggle (the
kill switch). When the agent wants a consequential action, an **Allow / Deny** banner appears
and the turn waits for your click — the same confirmation gate as the terminal, just in the
browser (it falls back to *deny* after the configured timeout, so it never hangs). The web
process also runs the heartbeat in the background, so one command gives you chat + proactivity.
Needs `ANTHROPIC_API_KEY`. Bound to `127.0.0.1` only — not exposed to your network.

**Voice in the browser:** when voice is enabled in `config.toml` (and the keys work), a 🎤
button appears. Click to record, click again to send — Gideon transcribes (Deepgram), runs the
turn, and speaks the reply back through your browser (ElevenLabs). The browser asks for mic
permission the first time; this works over `http` because `127.0.0.1` is a secure context.

**Run it at login (macOS):**

```bash
bash scripts/install-login-agent.sh             # start now + every login; restarts if it crashes
bash scripts/install-login-agent.sh uninstall   # stop + remove
```

Or double-click **`scripts/Start Gideon.command`** in Finder to launch it and open the browser.
Logs go to `state/web.log`.

**Use it from your phone / always-on:** see [DEPLOY.md](DEPLOY.md) — run Gideon 24/7 on a cloud
VPS or a Raspberry Pi (Docker), reachable privately from your devices over Tailscale. Exposing
it beyond localhost (`--host 0.0.0.0`) requires `GIDEON_WEB_PASSWORD`; the server refuses
otherwise, and remote access shows a login page.

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
| The face    | `web.py` (localhost chat UI)  | +    |

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
