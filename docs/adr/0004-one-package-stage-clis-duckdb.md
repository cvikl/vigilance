# One Python package with stage CLIs over DuckDB and files, not services

The hackathon rule requires the product be rebuilt on the day in under seven hours by up to three people. Every stage is `auditpace <stage>`, reading and writing parquet/JSON/PNG under `data/processed/`, queried through one DuckDB file. No queue, no database server, no build toolchain for the UI (FastAPI + one static page). Deployment shape for a trust (services, federation) is described in the pitch, not implemented.
