#!/bin/bash
# rotate_logs.sh - simple rotation for agent-dashboard out.log
# Keeps 7 compressed rotations, rotates atomically.
set -euo pipefail
LOG_DIR="/Users/virgolamobile/.openclaw/laboratory/agent-dashboard/logs"
LOG_FILE="$LOG_DIR/out.log"
ARCHIVE_DIR="$LOG_DIR/archive"
mkdir -p "$ARCHIVE_DIR"
# Timestamp
TS=$(date +"%Y%m%d-%H%M%S")
if [ -f "$LOG_FILE" ]; then
  # Move current log to archive with timestamp
  mv "$LOG_FILE" "$ARCHIVE_DIR/out.$TS.log"
  # Create new empty log file with same permissions
  touch "$LOG_FILE"
  chown $(whoami) "$LOG_FILE" || true
  chmod 644 "$LOG_FILE" || true
  # Compress the moved log
  gzip -9 "$ARCHIVE_DIR/out.$TS.log"
fi
# Remove older than 7 files
ls -1t "$ARCHIVE_DIR"/out.*.log.gz 2>/dev/null | tail -n +8 | xargs -r rm -f
