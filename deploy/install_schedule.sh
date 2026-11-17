#!/bin/bash
# Runs `python -m pipeline` every day at the time below, using macOS launchd.
# If the Mac is asleep at that time, the run starts when it wakes up.
#
#   bash deploy/install_schedule.sh            # install or update (default 08:00)
#   bash deploy/install_schedule.sh 7 30       # install for 07:30
#   bash deploy/install_schedule.sh --run-now  # start a run right away (to test)
#   bash deploy/install_schedule.sh --remove   # uninstall
#
# Log: data/logs/pipeline.log
set -euo pipefail

LABEL="com.ai-job-tracker.pipeline"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
DOMAIN="gui/$(id -u)"

if [[ "${1:-}" == "--remove" ]]; then
  launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
  rm -f "$PLIST"
  echo "Removed the daily run."
  exit 0
fi
if [[ "${1:-}" == "--run-now" ]]; then
  launchctl kickstart -p "$DOMAIN/$LABEL" && echo "Started. Follow it with: tail -f \"$REPO/data/logs/pipeline.log\""
  exit 0
fi

HOUR="${1:-8}"; MINUTE="${2:-0}"
PYTHON=""
for candidate in "$REPO/venv/bin/python" "$REPO/.venv/bin/python"; do
  [[ -x "$candidate" ]] && PYTHON="$candidate" && break
done
[[ -z "$PYTHON" ]] && { echo "No venv found in $REPO (venv/ or .venv/)."; exit 1; }

mkdir -p "$REPO/data/logs" "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>WorkingDirectory</key><string>$REPO</string>
  <key>ProgramArguments</key>
  <array><string>$PYTHON</string><string>-m</string><string>pipeline</string></array>
  <key>EnvironmentVariables</key>
  <dict><key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string></dict>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>$HOUR</integer><key>Minute</key><integer>$MINUTE</integer></dict>
  <key>StandardOutPath</key><string>$REPO/data/logs/pipeline.log</string>
  <key>StandardErrorPath</key><string>$REPO/data/logs/pipeline.log</string>
  <key>LowPriorityIO</key><true/>
</dict>
</plist>
PLIST

launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
launchctl bootstrap "$DOMAIN" "$PLIST"
printf "Daily run installed for %02d:%02d using %s\n" "$HOUR" "$MINUTE" "$PYTHON"
echo "Test it now with: bash deploy/install_schedule.sh --run-now"
