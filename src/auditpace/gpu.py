"""Pick the least-used GPU so every model process is pinned to exactly one device."""
import os
import subprocess

CANDIDATES = (0, 1, 2)


def pick_gpu(exclude: tuple[int, ...] = ()) -> int:
    out = subprocess.run(
        ["nvidia-smi", "--query-gpu=index,memory.used", "--format=csv,noheader,nounits"],
        check=True, capture_output=True, text=True,
    ).stdout
    rows = []
    for line in out.strip().splitlines():
        idx, used = (x.strip() for x in line.split(","))
        if int(idx) in CANDIDATES and int(idx) not in exclude:
            rows.append((int(used), int(idx)))
    if not rows:
        raise RuntimeError("no eligible GPU")
    return min(rows)[1]


def pin_gpu(exclude: tuple[int, ...] = ()) -> int:
    gpu = pick_gpu(exclude)
    os.environ["CUDA_VISIBLE_DEVICES"] = str(gpu)
    return gpu
