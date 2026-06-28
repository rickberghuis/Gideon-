# Gideon web face — host-agnostic image (runs the same on a cloud VPS or a Raspberry Pi).
# Browser voice works from here using only the Deepgram/ElevenLabs HTTP SDKs; the
# audio-hardware libs (PortAudio/X11) are intentionally NOT installed — they're only for
# the local push-to-talk path on your laptop.
FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1

# Install deps first for better layer caching.
COPY pyproject.toml ./
COPY src ./src
# Pre-install the build backend so the project install doesn't fetch it mid-build,
# and add retries/timeout so a transient PyPI blip doesn't fail the whole build.
RUN pip install --no-cache-dir --retries 5 --timeout 120 --upgrade pip setuptools wheel
RUN pip install --no-cache-dir --retries 5 --timeout 120 --no-build-isolation -e ".[server]"

# App config (tunables). Secrets come from the environment at runtime, never baked in.
COPY config.toml ./

EXPOSE 8000
# Listens on 0.0.0.0 inside the container; the host only publishes it to 127.0.0.1
# (see docker-compose.yml), and Tailscale serves it privately to your devices.
# --host 0.0.0.0 forces GIDEON_WEB_PASSWORD to be set (the server refuses otherwise).
CMD ["python", "-m", "gideon.main", "--web", "--host", "0.0.0.0"]
