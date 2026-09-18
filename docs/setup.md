# Setup

## Google Drive sync

Project folder: https://drive.google.com/drive/folders/1Nzx8oHYiHNPZ4GfqDYLKw0Dk8OmeITfy

One-time, on a machine with a browser:

```bash
rclone authorize "drive" "eyJzY29wZSI6ImRyaXZlLnJlYWRvbmx5In0"
```

Then on this server:

```bash
rclone config create auditpace drive scope=drive.readonly token='<paste JSON>'
```

Pull docs:

```bash
scripts/sync_drive.sh
```

`docs/drive/` is a read-only mirror. Edit in Drive, re-sync.

Push (write scope, separate remote so the read-only one stays safe): `rclone config create auditpace_rw drive scope=drive` in a VS Code terminal (answer `y` to the browser prompt — port 53682 auto-forwards; `n` to Shared Drive), then `scripts/push_drive.sh <dir>` copies a directory to the folder root and `rclone check`s it. Archives for the rebuild live at the folder root next to the Synthea zip; `REBUILD-MANIFEST-2026-09-18.md` there lists every file with its sha256 and restore command. rclone's shared `client_id` is being retired during 2026 — make your own (https://rclone.org/drive/#making-your-own-client-id) if either remote stops authorising.

## GitHub

No `gh` CLI on this host. Add an SSH key or set `GH_TOKEN` to push.

## Data

`data/raw/100k_synthea_covid19_csv.zip` (537MB) pulled by `scripts/sync_drive.sh`, unzipped to `data/synthea/100k_synthea_covid19_csv/` (4.8GB, 16 CSVs, 124k patients, 179k COVID condition rows). Both gitignored.

Source: Synthea COVID-19 100k dataset (Walonoski et al. 2020, manuscript in `docs/drive/`). Structured only — no free-text notes. Notes must be generated (NHS England pipeline cloned at `scripts/cloned_repos/synthetic_clinical_notes/`).

## Models (vLLM)

1. Accept the HAI-DEF licence on Hugging Face for `google/medgemma-27b-text-it` and the MedGemma 1.5 4B instruction-tuned model; `uv run hf auth login`.
2. `uv pip install -e ".[serve]"` (one-off, ~5 min).
3. `scripts/serve_medgemma.sh` → 27B on :8003 (8001 is taken by another tenant), 4B on :8002. Each model runs on exactly **one** GPU — no tensor parallelism. `scripts/pick_gpu.sh` chooses the GPU with the least `memory.used` (among candidates 0,1,2) at launch time, and the 4B model's pick excludes whichever GPU the 27B model landed on, so the two never collide. First run downloads ~60 GB to `$HF_HOME`.
4. `uv run auditpace models check`.
Stop: `pkill -f "vllm serve"`.
