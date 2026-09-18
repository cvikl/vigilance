#!/usr/bin/env bash
# Pull the project Google Drive folder. One-way: Drive -> local.
#   docs/drive/  <- documents (Google Docs exported as markdown)
#   data/raw/    <- bulk data archives (*.zip, *.gz, *.tar)
# Setup: rclone remote "auditpace" must exist (see docs/setup.md).
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:$PATH"
FOLDER_ID="1Nzx8oHYiHNPZ4GfqDYLKw0Dk8OmeITfy"
DATA_GLOB='{*.zip,*.gz,*.tar,*.tgz}'

rclone sync "auditpace:" docs/drive/ \
  --drive-root-folder-id "$FOLDER_ID" \
  --drive-export-formats md \
  --exclude "$DATA_GLOB" --exclude ".*" -q
rclone copy "auditpace:" data/raw/ \
  --drive-root-folder-id "$FOLDER_ID" \
  --include "$DATA_GLOB" --progress
echo "synced: docs/drive/ + data/raw/"
