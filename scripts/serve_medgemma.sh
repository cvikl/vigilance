#!/usr/bin/env bash
# Serve MedGemma 27B (text) and MedGemma 1.5 4B (multimodal) with vLLM, OpenAI-compatible.
# Prereq: uv pip install -e ".[serve]"; hf auth login (licence accepted on HF).
# ONLY=4b|27b|both (default both) starts a subset — S4 only needs the 4B reader.
# UTIL27 / UTIL4 override --gpu-memory-utilization (the GPUs are shared with other users).
# HF_HOME defaults to a per-user cache under /data: the system-wide /etc/profile.d value points
# at another user's read-only directory.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p data/logs
export HF_HOME="${AUDITPACE_HF_HOME:-/data/$USER/.cache/huggingface}"
M27="${M27:-google/medgemma-27b-text-it}"
M4="${M4:-google/medgemma-1.5-4b-it}"
ONLY="${ONLY:-both}"
# 27B listens on 8003: port 8001 is held by a foreign process on this host (S5 design R10).
# Fraction of each GPU vLLM may claim; GPUs are shared, so the 4B default leaves room for others.
UTIL27="${UTIL27:-0.92}"
UTIL4="${UTIL4:-0.50}"
# On a shared GPU with little free memory, --gpu-memory-utilization 0.92 / --max-model-len 16384
# (the defaults) can OOM. MAXLEN27 overrides the 27B context length; EAGER27=1 adds --enforce-eager
# (disables CUDA graphs, trading throughput for a smaller memory footprint). Known-good fallback on
# a GPU with ~67 GB free: UTIL27=0.66 MAXLEN27=12288 EAGER27=1 make serve.
MAXLEN27="${MAXLEN27:-16384}"
EAGER27="${EAGER27:-}"

GPU27=""
if [[ "$ONLY" == "both" || "$ONLY" == "27b" ]]; then
  GPU27=$(scripts/pick_gpu.sh); echo "27B → GPU $GPU27"
  EAGER27_FLAG=()
  [[ "$EAGER27" == "1" ]] && EAGER27_FLAG=(--enforce-eager)
  CUDA_VISIBLE_DEVICES=$GPU27 nohup uv run vllm serve "$M27" \
    --port 8003 --max-model-len "$MAXLEN27" \
    --gpu-memory-utilization "$UTIL27" --dtype bfloat16 "${EAGER27_FLAG[@]}" \
    > data/logs/vllm_27b.log 2>&1 &
  echo "27B → :8003 (log data/logs/vllm_27b.log)"
fi

if [[ "$ONLY" == "both" || "$ONLY" == "4b" ]]; then
  GPU4=$(scripts/pick_gpu.sh ${GPU27:+"$GPU27"}); echo "4B → GPU $GPU4"
  CUDA_VISIBLE_DEVICES=$GPU4 nohup uv run vllm serve "$M4" \
    --port 8002 --max-model-len 16384 --limit-mm-per-prompt '{"image": 4}' \
    --gpu-memory-utilization "$UTIL4" --dtype bfloat16 \
    > data/logs/vllm_4b.log 2>&1 &
  echo "4B → :8002 (log data/logs/vllm_4b.log)"
fi
echo "wait ~3-5 min then: uv run auditpace models check"
