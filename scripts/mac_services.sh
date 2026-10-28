#!/usr/bin/env bash
# Run ACE-Step and the queue worker in the background on this Mac, started at login and restarted
# if they crash (macOS launchd LaunchAgents).
#
#   scripts/mac_services.sh install     # create + start both services
#   scripts/mac_services.sh uninstall   # stop + remove them
#   scripts/mac_services.sh status
#
# Logs: ~/Library/Logs/housegen-acestep.log and ~/Library/Logs/housegen-worker.log
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AGENTS="$HOME/Library/LaunchAgents"
LOGS="$HOME/Library/Logs"
UV="$(command -v uv || echo /opt/homebrew/bin/uv)"
DOMAIN="gui/$(id -u)"
LABELS=(com.housegen.acestep com.housegen.worker)

plist() { # label, shell command
  cat <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$1</string>
  <key>ProgramArguments</key><array><string>/bin/zsh</string><string>-lc</string><string>$2</string></array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>30</integer>
  <key>StandardOutPath</key><string>$LOGS/${1/com./}.log</string>
  <key>StandardErrorPath</key><string>$LOGS/${1/com./}.log</string>
</dict></plist>
EOF
}

case "${1:-}" in
  install)
    mkdir -p "$AGENTS" "$LOGS"
    plist com.housegen.acestep "cd '$ROOT/ACE-Step-1.5' && ACESTEP_LM_BACKEND=mlx TOKENIZERS_PARALLELISM=false exec '$UV' run acestep-api --host 127.0.0.1 --port 8001" \
      > "$AGENTS/com.housegen.acestep.plist"
    plist com.housegen.worker "cd '$ROOT' && exec '$ROOT/.venv/bin/python' -u worker.py" \
      > "$AGENTS/com.housegen.worker.plist"
    for l in "${LABELS[@]}"; do
      launchctl bootout "$DOMAIN/$l" 2>/dev/null || true
      launchctl bootstrap "$DOMAIN" "$AGENTS/$l.plist"
    done
    echo "Installed. Logs in $LOGS/housegen-*.log"
    ;;
  uninstall)
    for l in "${LABELS[@]}"; do
      launchctl bootout "$DOMAIN/$l" 2>/dev/null || true
      rm -f "$AGENTS/$l.plist"
    done
    echo "Removed."
    ;;
  status)
    for l in "${LABELS[@]}"; do
      if launchctl print "$DOMAIN/$l" >/dev/null 2>&1; then
        echo "$l: $(launchctl print "$DOMAIN/$l" | awk '/state =/{print $3; exit}')"
      else
        echo "$l: not installed"
      fi
    done
    ;;
  *) echo "usage: $0 install|uninstall|status"; exit 1 ;;
esac
