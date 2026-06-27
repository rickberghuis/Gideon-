"""Push-to-talk capture.

Hold the configured key, speak, release. Push-to-talk means we never guess when speech
starts or ends — a huge simplification, and it stops Gideon from hearing itself (it isn't
capturing while it speaks). Returns 16 kHz mono PCM, which is what the STT seam wants.
"""

from __future__ import annotations

SAMPLE_RATE = 16000
CHANNELS = 1


def record_while_held(key_name: str = "space"):
    """Block until the key is pressed, record while held, return (pcm_bytes, sample_rate).

    Lazy-imports sounddevice + pynput so importing this module never requires audio libs."""
    import numpy as np
    import sounddevice as sd
    from pynput import keyboard

    target = _resolve_key(key_name, keyboard)
    frames: list = []
    state = {"recording": False, "done": False}

    def on_press(k):
        if _matches(k, target) and not state["recording"]:
            state["recording"] = True

    def on_release(k):
        if _matches(k, target) and state["recording"]:
            state["done"] = True
            return False  # stop the listener

    print(f"🎙️  Hold [{key_name}] to talk…", flush=True)
    with sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS, dtype="int16") as stream:
        with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
            while not state["done"]:
                if state["recording"]:
                    block, _ = stream.read(1024)
                    frames.append(block.copy())
                else:
                    sd.sleep(10)
            listener.join()

    if not frames:
        return b"", SAMPLE_RATE
    audio = np.concatenate(frames, axis=0)
    return audio.tobytes(), SAMPLE_RATE


def _resolve_key(name: str, keyboard):
    name = (name or "space").lower()
    special = {
        "space": keyboard.Key.space,
        "ctrl": keyboard.Key.ctrl,
        "shift": keyboard.Key.shift,
        "alt": keyboard.Key.alt,
        "cmd": keyboard.Key.cmd,
    }
    if name in special:
        return special[name]
    return keyboard.KeyCode.from_char(name[0])


def _matches(k, target) -> bool:
    try:
        return k == target or getattr(k, "char", None) == getattr(target, "char", None)
    except Exception:
        return False
