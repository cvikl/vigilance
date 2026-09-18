#!/usr/bin/env bash
# Push rebuild materials to the project Google Drive folder. One-way: local -> Drive.
# Needs a WRITE-scope rclone remote "auditpace_rw" (the "auditpace" remote is read-only).
# One-time setup, in an interactive VS Code terminal (port 53682 auto-forwards):
#   rclone config create auditpace_rw drive scope=drive
#   -> answer "y" to "Use web browser to automatically authenticate", open the printed link.
# Usage: scripts/push_drive.sh <stage-dir>
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
FOLDER_ID="1Nzx8oHYiHNPZ4GfqDYLKw0Dk8OmeITfy"
STAGE="${1:?stage dir}"
rclone copy "$STAGE" "auditpace_rw:" \
  --drive-root-folder-id "$FOLDER_ID" \
  --copy-links --checksum --transfers 4 --progress
echo "--- verify"
rclone check "$STAGE" "auditpace_rw:" --drive-root-folder-id "$FOLDER_ID" --copy-links --one-way
