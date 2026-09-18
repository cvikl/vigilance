#!/usr/bin/env bash
# Print the index of the least-used GPU (among 0,1,2), excluding any indices given as args.
set -euo pipefail
exclude_re="^($(IFS='|'; echo "${*:-none}"))$"
nvidia-smi --query-gpu=index,memory.used --format=csv,noheader,nounits \
  | grep -E '^[012],' | awk -F', *' -v re="$exclude_re" '$1 !~ re {print $2","$1}' \
  | sort -n | head -n1 | cut -d, -f2
