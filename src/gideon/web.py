"""The face — a local browser chat UI at http://127.0.0.1:<port>.

Another way IN to the same agent core (Agent.send). Built on the standard library's
http.server (no web framework) so the harness stays small. Single-user, localhost-only.

The notable piece is the web confirmation gate: a browser can't answer a terminal prompt,
so WebConfirmer surfaces the pending action to the page and blocks the turn until the user
clicks Allow/Deny — or until the configured timeout, which falls back to the safe default
(deny). That reuses the Tier 5/6 rule: never block forever waiting on a human.

A background thread also beats the heartbeat, so one `gideon --web` gives you chat + the
proactive inbox in one place.
"""

from __future__ import annotations

import json
import os
import secrets
import threading
import uuid
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .config import load_config
from .heartbeat import run_background
from .safety import engage_kill_switch, kill_switch_engaged, release_kill_switch


# --- web confirmation gate ---------------------------------------------------------------

class WebConfirmer:
    """Surfaces one pending gated action to the browser and waits for the verdict."""

    def __init__(self, timeout_seconds: float) -> None:
        self._lock = threading.Lock()
        self._event = threading.Event()
        self._pending: dict[str, Any] | None = None
        self._result = False
        self._timeout = timeout_seconds

    def __call__(self, name: str, payload: dict[str, Any], summary: str) -> bool:
        with self._lock:
            self._pending = {
                "id": uuid.uuid4().hex[:8],
                "tool": name,
                "args": payload,
                "summary": summary,
            }
            self._result = False
            self._event.clear()
        answered = self._event.wait(self._timeout)
        with self._lock:
            result = self._result if answered else False  # timeout -> safe default: deny
            self._pending = None
        return result

    def resolve(self, confirmation_id: str, allow: bool) -> bool:
        with self._lock:
            if self._pending and self._pending["id"] == confirmation_id:
                self._result = allow
                self._event.set()
                return True
        return False

    def snapshot(self) -> dict[str, Any] | None:
        with self._lock:
            return dict(self._pending) if self._pending else None


# --- shared app state --------------------------------------------------------------------

class _App:
    def __init__(self) -> None:
        from .main import build_agent  # local import avoids a cycle at module load

        config = load_config()
        timeout = float(config.heartbeat.get("approval_timeout_seconds", 120))
        self.confirmer = WebConfirmer(timeout)
        self.agent, self.audit, self.memory, self.inbox = build_agent(confirmer=self.confirmer)
        self.turn_lock = threading.Lock()  # one conversational turn at a time
        self.voice_enabled = bool(config.voice.get("enabled"))
        self._transcriber = None
        self._speaker = None
        # Auth: a password gate for remote access. Empty password => auth off (local only).
        self.password = os.environ.get("GIDEON_WEB_PASSWORD", "")
        self.sessions: set[str] = set()

    def _voice_components(self):
        """Lazily build STT/TTS so a missing audio dep only breaks voice, not the whole face."""
        if self._transcriber is None:
            from .voice.stt import Transcriber
            from .voice.tts import Speaker

            cfg = load_config()
            self._transcriber = Transcriber(cfg)
            self._speaker = Speaker(cfg)
        return self._transcriber, self._speaker

    def handle_voice(self, audio_bytes: bytes) -> dict[str, Any]:
        """Browser mic → transcript → same agent core → spoken reply (mp3, base64)."""
        import base64

        transcriber, speaker = self._voice_components()
        heard = transcriber.transcribe_audio(audio_bytes)
        if not heard:
            return {"transcript": "", "reply": "", "error": "Didn't catch that."}
        with self.turn_lock:
            reply = self.agent.send(heard)
        out: dict[str, Any] = {"transcript": heard, "reply": reply}
        try:
            mp3 = speaker.synthesize_mp3(reply)
            out["audio"] = base64.b64encode(mp3).decode("ascii")
        except Exception as exc:
            out["tts_error"] = str(exc)[:200]  # reply still shows as text
        return out

    def state(self) -> dict[str, Any]:
        return {
            "pending": self.confirmer.snapshot(),
            "inbox": [
                {"id": i["id"], "text": i["text"], "severity": i["severity"]}
                for i in self.inbox.pending()
            ],
            "kill": kill_switch_engaged(load_config()),
            "cost": round(self.audit.session_cost_usd, 4),
            "voice": self.voice_enabled,
        }


APP: _App | None = None


# --- HTTP handler ------------------------------------------------------------------------

class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # quiet the default request logging
        pass

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: dict[str, Any], code: int = 200) -> None:
        self._send(code, json.dumps(payload).encode("utf-8"), "application/json")

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", 0))
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    # --- auth helpers ---
    def _authed(self) -> bool:
        if not APP.password:  # no password configured => local, auth disabled
            return True
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        token = cookie["gideon_session"].value if "gideon_session" in cookie else ""
        return bool(token) and token in APP.sessions

    def do_GET(self) -> None:
        if not self._authed():
            if self.path == "/" or self.path.startswith("/index"):
                self._send(200, _LOGIN_HTML.encode("utf-8"), "text/html; charset=utf-8")
            else:
                self._json({"error": "unauthorized"}, 401)
            return
        if self.path == "/" or self.path.startswith("/index"):
            self._send(200, _INDEX_HTML.encode("utf-8"), "text/html; charset=utf-8")
        elif self.path == "/state":
            self._json(APP.state())
        else:
            self._send(404, b"not found", "text/plain")

    def _read_raw(self) -> bytes:
        length = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(length) if length else b""

    def _login(self, body: dict[str, Any]) -> None:
        ok = bool(APP.password) and secrets.compare_digest(
            str(body.get("password", "")), APP.password
        )
        if not ok:
            self._json({"ok": False}, 401)
            return
        token = secrets.token_urlsafe(24)
        APP.sessions.add(token)
        payload = json.dumps({"ok": True}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header(
            "Set-Cookie", f"gideon_session={token}; HttpOnly; SameSite=Lax; Path=/"
        )
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self) -> None:
        if self.path == "/login":
            self._login(self._read_json())
            return
        if not self._authed():
            self._json({"error": "unauthorized"}, 401)
            return
        if self.path == "/voice":
            audio = self._read_raw()
            try:
                self._json(APP.handle_voice(audio))
            except RuntimeError as exc:  # missing key / voice id
                self._json({"error": str(exc)})
            except Exception as exc:
                self._json({"error": f"voice failed: {str(exc)[:200]}"})
            return

        body = self._read_json()
        if self.path == "/chat":
            message = (body.get("message") or "").strip()
            if not message:
                self._json({"reply": ""})
                return
            with APP.turn_lock:  # serialize turns; /confirm + /state stay concurrent
                reply = APP.agent.send(message)
            self._json({"reply": reply})
        elif self.path == "/confirm":
            ok = APP.confirmer.resolve(body.get("id", ""), bool(body.get("allow")))
            self._json({"ok": ok})
        elif self.path == "/dismiss":
            APP.inbox.dismiss(body.get("id", ""))
            self._json({"ok": True})
        elif self.path == "/kill":
            msg = engage_kill_switch() if body.get("on") else release_kill_switch()
            self._json({"ok": True, "message": msg})
        else:
            self._send(404, b"not found", "text/plain")


def run_web(port: int = 8000, host: str = "127.0.0.1") -> None:
    global APP
    # Safety: never expose an unauthenticated agent beyond this machine.
    if host != "127.0.0.1" and not os.environ.get("GIDEON_WEB_PASSWORD"):
        print(
            "❌ Refusing to bind to a non-local address without a password.\n"
            "   Set GIDEON_WEB_PASSWORD in .env before exposing Gideon "
            "(and keep it behind Tailscale)."
        )
        return

    APP = _App()  # constructs the agent (needs ANTHROPIC_API_KEY)

    stop_event = threading.Event()
    threading.Thread(target=run_background, args=(stop_event,), daemon=True).start()

    server = ThreadingHTTPServer((host, port), _Handler)
    shown = "127.0.0.1" if host in ("127.0.0.1", "0.0.0.0") else host
    auth = "password-protected" if APP.password else "local, no password"
    print(f"🌐 Gideon's face is live at http://{shown}:{port}  ({auth}; Ctrl-C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nbye 👋")
    finally:
        stop_event.set()
        server.shutdown()


# --- the UI (single self-contained page) -------------------------------------------------

_LOGIN_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Gideon — sign in</title>
<style>
  body { margin:0; height:100vh; display:flex; align-items:center; justify-content:center;
         background:#0f1115; color:#e7e9ee; font:15px -apple-system,Segoe UI,Roboto,sans-serif; }
  .card { background:#171a21; border:1px solid #262b36; border-radius:14px; padding:28px; width:300px; }
  h1 { font-size:18px; margin:0 0 4px; } p { color:#8b93a7; font-size:13px; margin:0 0 18px; }
  input { width:100%; box-sizing:border-box; background:#0f1115; border:1px solid #262b36;
          color:#e7e9ee; border-radius:8px; padding:10px 12px; font:inherit; }
  button { width:100%; margin-top:12px; background:#2563eb; color:#fff; border:none;
           border-radius:8px; padding:10px; font-weight:600; cursor:pointer; }
  .err { color:#ff9b9b; font-size:13px; margin-top:10px; min-height:18px; }
</style></head>
<body>
  <div class="card">
    <h1>Gideon</h1><p>Enter your password to continue.</p>
    <input id="pw" type="password" placeholder="Password" autofocus
           onkeydown="if(event.key==='Enter')go()">
    <button onclick="go()">Sign in</button>
    <div class="err" id="err"></div>
  </div>
<script>
async function go(){
  const pw = document.getElementById('pw').value;
  const r = await fetch('/login', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({password: pw})});
  if (r.ok) { location.href = '/'; }
  else { document.getElementById('err').textContent = 'Wrong password.'; }
}
</script>
</body></html>
"""

_INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Gideon</title>
<style>
  :root { --bg:#0f1115; --panel:#171a21; --me:#2563eb; --bot:#222733; --text:#e7e9ee;
          --muted:#8b93a7; --warn:#3a2a12; --warnb:#b9821f; --line:#262b36; }
  * { box-sizing:border-box; }
  body { margin:0; font:15px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;
         background:var(--bg); color:var(--text); height:100vh; display:flex; }
  #wrap { display:flex; flex-direction:column; flex:1; max-width:760px; margin:0 auto; height:100vh; }
  header { padding:14px 18px; border-bottom:1px solid var(--line); display:flex;
           align-items:center; gap:10px; }
  header h1 { font-size:16px; margin:0; font-weight:600; }
  header .sub { color:var(--muted); font-size:12px; }
  header .right { margin-left:auto; display:flex; gap:10px; align-items:center; font-size:12px; }
  #kill { cursor:pointer; border:1px solid var(--line); background:var(--panel); color:var(--text);
          padding:4px 10px; border-radius:6px; }
  #kill.on { background:#3a1212; border-color:#7a2a2a; color:#ffb4b4; }
  #inbox { padding:0 18px; }
  .notice { background:var(--panel); border:1px solid var(--line); border-radius:8px;
            padding:8px 10px; margin-top:10px; display:flex; gap:8px; align-items:center; font-size:13px; }
  .notice button { margin-left:auto; }
  #log { flex:1; overflow-y:auto; padding:18px; display:flex; flex-direction:column; gap:12px; }
  .msg { max-width:80%; padding:9px 13px; border-radius:14px; white-space:pre-wrap; word-wrap:break-word; }
  .me { background:var(--me); color:#fff; align-self:flex-end; border-bottom-right-radius:4px; }
  .bot { background:var(--bot); align-self:flex-start; border-bottom-left-radius:4px; }
  .who { font-size:11px; color:var(--muted); margin:0 4px -6px; }
  .me-who { align-self:flex-end; } .bot-who { align-self:flex-start; }
  #confirm { margin:0 18px; background:var(--warn); border:1px solid var(--warnb);
             border-radius:10px; padding:12px 14px; display:none; }
  #confirm h3 { margin:0 0 6px; font-size:14px; color:#ffd58a; }
  #confirm .args { color:var(--muted); font-size:12px; margin:6px 0 10px; word-break:break-all; }
  #confirm .row { display:flex; gap:8px; }
  button { cursor:pointer; border:none; border-radius:7px; padding:7px 14px; font-size:13px;
           font-weight:600; }
  .allow { background:#1f7a3d; color:#fff; } .deny { background:#7a2a2a; color:#fff; }
  .dismiss { background:var(--bot); color:var(--text); padding:4px 10px; }
  footer { padding:12px 18px; border-top:1px solid var(--line); display:flex; gap:10px; }
  #in { flex:1; resize:none; background:var(--panel); border:1px solid var(--line);
        color:var(--text); border-radius:10px; padding:10px 12px; font:inherit; max-height:120px; }
  #send { background:var(--me); color:#fff; }
  #send:disabled, #mic:disabled { opacity:.5; cursor:default; }
  #mic { background:var(--bot); color:var(--text); font-size:16px; }
  #mic.rec { background:#7a2a2a; color:#fff; animation:pulse 1s infinite; }
  @keyframes pulse { 50% { opacity:.55; } }
  .typing { color:var(--muted); font-style:italic; }
</style>
</head>
<body>
<div id="wrap">
  <header>
    <h1>Gideon</h1>
    <span class="sub">local · 127.0.0.1</span>
    <div class="right">
      <span id="cost"></span>
      <span id="kill" title="Pause all proactive behavior">heartbeat: on</span>
    </div>
  </header>
  <div id="inbox"></div>
  <div id="confirm">
    <h3 id="confirm-summary"></h3>
    <div class="args" id="confirm-args"></div>
    <div class="row">
      <button class="allow" onclick="resolveConfirm(true)">Allow</button>
      <button class="deny" onclick="resolveConfirm(false)">Deny</button>
    </div>
  </div>
  <div id="log"></div>
  <footer>
    <textarea id="in" rows="1" placeholder="Talk to Gideon…  (Enter to send)"></textarea>
    <button id="mic" title="Click to talk, click again to send" style="display:none">🎤</button>
    <button id="send" onclick="send()">Send</button>
  </footer>
</div>
<script>
const log = document.getElementById('log');
const input = document.getElementById('in');
const sendBtn = document.getElementById('send');
let pendingId = null;

function bubble(text, who) {
  const w = document.createElement('div');
  w.className = 'who ' + (who === 'me' ? 'me-who' : 'bot-who');
  w.textContent = who === 'me' ? 'you' : 'gideon';
  const m = document.createElement('div');
  m.className = 'msg ' + (who === 'me' ? 'me' : 'bot');
  m.textContent = text;
  log.appendChild(w); log.appendChild(m);
  log.scrollTop = log.scrollHeight;
  return m;
}

async function send() {
  const text = input.value.trim();
  if (!text) return;
  input.value = ''; input.style.height = 'auto';
  bubble(text, 'me');
  sendBtn.disabled = true;
  const typing = bubble('thinking…', 'bot'); typing.classList.add('typing');
  try {
    const r = await fetch('/chat', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({message: text})});
    const data = await r.json();
    typing.classList.remove('typing');
    typing.textContent = data.reply || '(no reply)';
  } catch (e) {
    typing.classList.remove('typing');
    typing.textContent = '⚠️ could not reach the server';
  } finally {
    sendBtn.disabled = false; input.focus();
    refresh();
  }
}

async function resolveConfirm(allow) {
  if (!pendingId) return;
  await fetch('/confirm', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({id: pendingId, allow})});
  document.getElementById('confirm').style.display = 'none';
  pendingId = null;
}

async function dismiss(id) {
  await fetch('/dismiss', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({id})});
  refresh();
}

async function toggleKill() {
  const on = !document.getElementById('kill').classList.contains('on');
  await fetch('/kill', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({on})});
  refresh();
}
document.getElementById('kill').onclick = toggleKill;

async function refresh() {
  let s;
  try { s = await (await fetch('/state')).json(); } catch (e) { return; }
  // confirmation
  const box = document.getElementById('confirm');
  if (s.pending) {
    pendingId = s.pending.id;
    document.getElementById('confirm-summary').textContent = '⚠️ ' + s.pending.summary + '?';
    document.getElementById('confirm-args').textContent =
      s.pending.tool + '  ' + JSON.stringify(s.pending.args);
    box.style.display = 'block';
  } else if (!pendingId) {
    box.style.display = 'none';
  }
  // inbox
  const inbox = document.getElementById('inbox');
  inbox.innerHTML = '';
  (s.inbox || []).forEach(n => {
    const d = document.createElement('div'); d.className = 'notice';
    const flag = n.severity === 'critical' ? '‼️' : (n.severity === 'interrupt' ? '❗' : '•');
    const t = document.createElement('span'); t.textContent = flag + ' ' + n.text;
    const b = document.createElement('button'); b.className = 'dismiss'; b.textContent = 'dismiss';
    b.onclick = () => dismiss(n.id);
    d.appendChild(t); d.appendChild(b); inbox.appendChild(d);
  });
  // kill + cost
  const kill = document.getElementById('kill');
  kill.classList.toggle('on', !!s.kill);
  kill.textContent = s.kill ? 'heartbeat: paused' : 'heartbeat: on';
  document.getElementById('cost').textContent = '$' + (s.cost || 0).toFixed(4);
  document.getElementById('mic').style.display = s.voice ? 'block' : 'none';
}

// --- voice: click mic to record, click again to send ---
const mic = document.getElementById('mic');
let mediaRecorder = null, chunks = [], recording = false;

mic.onclick = () => recording ? stopRec() : startRec();

async function startRec() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({audio: true});
    mediaRecorder = new MediaRecorder(stream);
    chunks = [];
    mediaRecorder.ondataavailable = e => { if (e.data.size > 0) chunks.push(e.data); };
    mediaRecorder.onstop = async () => {
      stream.getTracks().forEach(t => t.stop());
      await sendVoice(new Blob(chunks, {type: mediaRecorder.mimeType || 'audio/webm'}));
    };
    mediaRecorder.start();
    recording = true; mic.classList.add('rec'); mic.textContent = '⏹';
  } catch (e) { bubble('⚠️ microphone permission denied', 'bot'); }
}

function stopRec() {
  if (mediaRecorder && recording) {
    mediaRecorder.stop(); recording = false;
    mic.classList.remove('rec'); mic.textContent = '🎤';
  }
}

async function sendVoice(blob) {
  sendBtn.disabled = true; mic.disabled = true;
  const meMsg = bubble('🎤 …', 'me');
  const typing = bubble('listening…', 'bot'); typing.classList.add('typing');
  try {
    const r = await fetch('/voice', {method: 'POST',
      headers: {'Content-Type': blob.type || 'audio/webm'}, body: blob});
    const data = await r.json();
    typing.classList.remove('typing');
    if (data.error) { meMsg.textContent = '🎤'; typing.textContent = '⚠️ ' + data.error; }
    else {
      meMsg.textContent = data.transcript || '(unclear)';
      typing.textContent = data.reply || '(no reply)';
      if (data.audio) new Audio('data:audio/mp3;base64,' + data.audio).play();
    }
  } catch (e) {
    typing.classList.remove('typing'); typing.textContent = '⚠️ voice request failed';
  } finally { sendBtn.disabled = false; mic.disabled = false; refresh(); }
}

input.addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
});
input.addEventListener('input', () => {
  input.style.height = 'auto'; input.style.height = Math.min(input.scrollHeight, 120) + 'px';
});
setInterval(refresh, 1200);
refresh(); input.focus();
</script>
</body>
</html>
"""
