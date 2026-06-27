#!/usr/bin/env bash
# Double-click this in Finder to start Gideon's web face, then it opens your browser.
cd "$(dirname "$0")/.."
source .venv/bin/activate
( sleep 1.5 && open "http://127.0.0.1:8000" ) &
exec python -m gideon.main --web
