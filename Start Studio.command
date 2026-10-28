#!/bin/zsh
# Double-click in Finder to open the studio: starts ACE-Step + the queue worker so songs requested
# on the website get made. Close this window (or press Ctrl+C) to stop both.
cd "$(dirname "$0")"
ROOT="$PWD"
mkdir -p output/logs
ACE_LOG="$ROOT/output/logs/acestep.log"
ACE_PID=""

cleanup() {
  echo "\nStopping studio…"
  [[ -n "$ACE_PID" ]] && kill "$ACE_PID" 2>/dev/null && wait "$ACE_PID" 2>/dev/null
  echo "Stopped. New songs will wait in the queue until you start the studio again."
}
trap cleanup EXIT INT TERM HUP

echo "═══ House Music Generator — studio ═══"

if curl -sf http://127.0.0.1:8001/health >/dev/null; then
  echo "ACE-Step already running."
else
  echo "Starting ACE-Step (log: output/logs/acestep.log)…"
  # Pin the regular turbo model: the XL one sounded no better in tests and runs this Mac out of memory.
  (cd ACE-Step-1.5 && ACESTEP_CONFIG_PATH=acestep-v15-turbo ACESTEP_LM_BACKEND=mlx TOKENIZERS_PARALLELISM=false \
    exec "$(command -v uv || echo /opt/homebrew/bin/uv)" run acestep-api --host 127.0.0.1 --port 8001) >"$ACE_LOG" 2>&1 &
  ACE_PID=$!
  until curl -sf http://127.0.0.1:8001/health >/dev/null; do
    if ! kill -0 "$ACE_PID" 2>/dev/null; then
      echo "ACE-Step failed to start — last log lines:"; tail -20 "$ACE_LOG"; exit 1
    fi
    sleep 2
  done
  echo "ACE-Step ready."
fi

# Keep the Mac from idle-sleeping while the studio is open (closing the lid on battery still sleeps).
caffeinate -i -w $$ &

echo "Worker running — songs requested on the website will be made here. Close this window to stop.\n"
.venv/bin/python -u worker.py
