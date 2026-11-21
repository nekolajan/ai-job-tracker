#!/bin/bash
# Runs `python -m pipeline` every day at the times below, using macOS launchd.
# If the Mac is asleep at that time, the run starts when it wakes up.
# Scraping happens only in the first run of the day; later runs catch up on
# extraction (handy when the Mac slept through the morning run).
# While it runs, `caffeinate -i` stops the Mac from falling asleep when idle
# (closing the lid still puts it to sleep).
#
#   bash deploy/install_schedule.sh                 # install or update (default 09:30 and 14:00)
#   bash deploy/install_schedule.sh 8:00 12:30 18:00 # any times, HH:MM
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

TIMES=("$@")
[[ ${#TIMES[@]} -eq 0 ]] && TIMES=("09:30" "14:00")
INTERVALS=""
for t in "${TIMES[@]}"; do
  [[ "$t" =~ ^([0-9]{1,2}):([0-9]{2})$ ]] || { echo "Times must look like 9:30 or 14:00, got '$t'"; exit 1; }
  H=$((10#${BASH_REMATCH[1]})); M=$((10#${BASH_REMATCH[2]}))
  INTERVALS+="    <dict><key>Hour</key><integer>$H</integer><key>Minute</key><integer>$M</integer></dict>"$'\n'
done
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
  <array><string>/usr/bin/caffeinate</string><string>-i</string><string>$PYTHON</string><string>-u</string><string>-m</string><string>pipeline</string></array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    <key>PYTHONUNBUFFERED</key><string>1</string>
  </dict>
  <key>StartCalendarInterval</key>
  <array>
$INTERVALS  </array>
  <key>StandardOutPath</key><string>$REPO/data/logs/pipeline.log</string>
  <key>StandardErrorPath</key><string>$REPO/data/logs/pipeline.log</string>
  <key>LowPriorityIO</key><true/>
</dict>
</plist>
PLIST

launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
launchctl bootstrap "$DOMAIN" "$PLIST"
echo "Daily runs installed for ${TIMES[*]} using $PYTHON"
echo "Test it now with: bash deploy/install_schedule.sh --run-now"
