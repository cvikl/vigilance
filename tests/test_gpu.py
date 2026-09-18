import os
from dataclasses import dataclass

import pytest

from auditpace import gpu


@dataclass
class _FakeCompletedProcess:
    stdout: str


def _fake_run(*args, **kwargs):
    return _FakeCompletedProcess(stdout="0, 40000\n1, 100\n2, 5000\n")


@pytest.fixture(autouse=True)
def _no_real_nvidia_smi(monkeypatch):
    monkeypatch.setattr(gpu.subprocess, "run", _fake_run)


def test_pick_gpu_returns_least_used():
    assert gpu.pick_gpu() == 1


def test_pick_gpu_excludes_given_indices():
    assert gpu.pick_gpu(exclude=(1,)) == 2


def test_pin_gpu_sets_cuda_visible_devices(monkeypatch):
    # pin_gpu mutates os.environ directly; swap in a throwaway copy so monkeypatch's
    # teardown restores the real environment regardless of what pin_gpu does to it.
    monkeypatch.setattr(os, "environ", os.environ.copy())
    monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)
    assert gpu.pin_gpu() == 1
    assert os.environ["CUDA_VISIBLE_DEVICES"] == "1"
