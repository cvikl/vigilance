.PHONY: test lint serve check fixture
export AUDITPACE_MOCK ?= 1
export HF_HOME ?= /data/$(USER)/.cache/huggingface

test:
	AUDITPACE_RECORD= uv run pytest

lint:
	uv run ruff check src tests scripts

serve:
	AUDITPACE_MOCK=0 scripts/serve_medgemma.sh

demo-reset:
	scripts/demo_reset.sh

check:
	AUDITPACE_MOCK=0 uv run auditpace models check

fixture:
	uv run python scripts/make_mini_fixture.py
