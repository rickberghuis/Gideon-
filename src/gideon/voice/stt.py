"""Speech-to-text seam — Deepgram.

One job: give me audio, get back text. Swap the provider here without touching the agent.
PCM bytes go in (16 kHz mono int16); a transcript string comes out.
"""

from __future__ import annotations

from ..config import Config, require_env


class Transcriber:
    def __init__(self, config: Config) -> None:
        self._config = config
        self._model = config.voice.get("deepgram_model", "nova-2")
        from deepgram import DeepgramClient  # lazy import (deepgram-sdk 6.x)

        self._client = DeepgramClient(api_key=require_env("DEEPGRAM_API_KEY"))

    def transcribe(self, pcm_bytes: bytes, sample_rate: int) -> str:
        if not pcm_bytes:
            return ""
        # Wrap raw PCM in a WAV container so Deepgram auto-detects rate/encoding.
        return self.transcribe_audio(_wrap_pcm_as_wav(pcm_bytes, sample_rate))

    def transcribe_audio(self, audio_bytes: bytes) -> str:
        """Transcribe already-containerized audio (WAV/WebM/OGG/MP3 — e.g. browser mic
        recordings). Deepgram auto-detects the container."""
        if not audio_bytes:
            return ""
        response = self._client.listen.v1.media.transcribe_file(
            request=audio_bytes,
            model=self._model,
            smart_format=True,
            language="en",
        )
        try:
            return response.results.channels[0].alternatives[0].transcript.strip()
        except (AttributeError, IndexError):
            return ""


def _wrap_pcm_as_wav(pcm_bytes: bytes, sample_rate: int) -> bytes:
    import io
    import wave

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # int16
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_bytes)
    return buf.getvalue()
