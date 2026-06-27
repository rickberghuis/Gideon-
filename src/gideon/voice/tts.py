"""Text-to-speech seam — ElevenLabs.

One job: give me text, play it aloud. Streams PCM so playback can begin before the whole
sentence is synthesized, and checks a stop flag between chunks so the user can interrupt
(barge-in). Swap the provider or voice here; the voice id lives in config.toml.
"""

from __future__ import annotations

import re
import threading
from typing import Callable

from ..config import Config, require_env

_PCM_RATE = 16000  # request raw PCM at 16 kHz so we can play + interrupt cleanly


class Speaker:
    def __init__(self, config: Config) -> None:
        v = config.voice
        self._voice_id = v.get("elevenlabs_voice_id") or ""
        self._model = v.get("elevenlabs_model", "eleven_turbo_v2_5")
        from elevenlabs.client import ElevenLabs  # lazy import

        self._client = ElevenLabs(api_key=require_env("ELEVENLABS_API_KEY"))
        self._stop = threading.Event()

    def interrupt(self) -> None:
        """Stop current playback ASAP (barge-in)."""
        self._stop.set()

    @property
    def voice_id(self) -> str:
        return self._voice_id

    def synthesize_bytes(self, text: str) -> bytes:
        """Synthesize the whole line to PCM bytes (no playback). Raises on API errors,
        so a permission/key problem surfaces cleanly. Used by `gideon --voice-check`."""
        if not self._voice_id:
            raise RuntimeError("No elevenlabs_voice_id set in config.toml")
        audio = self._client.text_to_speech.convert(
            voice_id=self._voice_id,
            model_id=self._model,
            text=text,
            output_format="pcm_16000",
        )
        return b"".join(chunk for chunk in audio if chunk)

    def synthesize_mp3(self, text: str) -> bytes:
        """Synthesize to MP3 bytes — what the browser face plays directly via an <audio>."""
        if not self._voice_id:
            raise RuntimeError("No elevenlabs_voice_id set in config.toml")
        audio = self._client.text_to_speech.convert(
            voice_id=self._voice_id,
            model_id=self._model,
            text=text,
            output_format="mp3_44100_128",
        )
        return b"".join(chunk for chunk in audio if chunk)

    def play_pcm(self, pcm: bytes) -> None:
        """Play raw 16 kHz mono PCM. Separate from synth so playback errors (no audio
        device) don't get confused with synthesis errors."""
        import numpy as np
        import sounddevice as sd

        sd.play(np.frombuffer(pcm, dtype="int16"), _PCM_RATE)
        sd.wait()

    def speak(self, text: str) -> None:
        """Synthesize and play `text`, returning when done or interrupted."""
        text = text.strip()
        if not text or not self._voice_id:
            return
        self._stop.clear()
        import numpy as np
        import sounddevice as sd

        audio = self._client.text_to_speech.convert(
            voice_id=self._voice_id,
            model_id=self._model,
            text=text,
            output_format="pcm_16000",
        )
        with sd.RawOutputStream(samplerate=_PCM_RATE, channels=1, dtype="int16") as stream:
            for chunk in audio:
                if self._stop.is_set():
                    break
                if chunk:
                    stream.write(chunk)


def sentence_chunks(stream_text: Callable[[], str]):
    """Helper for early speech: buffer streamed text and yield complete sentences as they
    form, so TTS can start on sentence 1 while the model still writes the rest."""
    buffer = ""
    sentence_end = re.compile(r"(.+?[.!?])(\s|$)")
    while True:
        piece = stream_text()
        if piece is None:
            break
        buffer += piece
        while True:
            m = sentence_end.match(buffer)
            if not m:
                break
            yield m.group(1).strip()
            buffer = buffer[m.end():]
    if buffer.strip():
        yield buffer.strip()
