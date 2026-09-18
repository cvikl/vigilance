"""Project settings loaded from config.yaml. No secrets here; HF token lives in the env."""
import os
from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class ModelEndpoint(BaseModel):
    base_url: str
    model: str
    api_key: str = "EMPTY"  # vLLM ignores it; Anthropic-compatible proxies may not


class Paths(BaseModel):
    synthea_dir: Path
    processed_dir: Path
    fixtures_dir: Path


class Models(BaseModel):
    adjudicator: ModelEndpoint | None = None
    reader: ModelEndpoint | None = None
    designer: ModelEndpoint | None = None
    reporter: ModelEndpoint | None = None


class SynthConfig(BaseModel):
    """Stage 2 document authoring via `claude -p` (ADR 0003)."""
    model: str = "sonnet"
    batch_size: int = 5
    workers: int = 8
    timeout_s: int = 600


class RenderConfig(BaseModel):
    """Stage 3 page rendering (S3 design §8)."""
    workers: int = 4


class ReadConfig(BaseModel):
    """Stage 4 reading (S4 design §3)."""
    workers: int = 8
    max_tokens: int = 1024
    tessdata_dir: Path = Path("data/tessdata")


class AdjudicateConfig(BaseModel):
    """Stage 5 adjudication (S5 design §3)."""
    workers: int = 8
    max_tokens: int = 1024


class Settings(BaseModel):
    paths: Paths
    models: Models = Field(default_factory=Models)
    synth: SynthConfig = Field(default_factory=SynthConfig)
    render: RenderConfig = Field(default_factory=RenderConfig)
    read: ReadConfig = Field(default_factory=ReadConfig)
    adjudicate: AdjudicateConfig = Field(default_factory=AdjudicateConfig)
    seed: int = 42
    mock: bool = False


def load_settings(path: Path | None = None) -> Settings:
    path = Path(path or os.environ.get("AUDITPACE_CONFIG", "config.yaml"))
    data = yaml.safe_load(path.read_text()) or {}
    data["mock"] = os.environ.get("AUDITPACE_MOCK", "0") == "1"
    return Settings.model_validate(data)
