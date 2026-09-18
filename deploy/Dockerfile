# vigilance workbench — serves the clinician UI over pre-computed pipeline outputs.
FROM python:3.12-slim
WORKDIR /srv
RUN pip install --no-cache-dir \
      "typer>=0.12" "pydantic>=2.7" "pyyaml>=6" "duckdb>=1.1" "pyarrow>=17" "pandas>=2.2" "httpx>=0.27" \
      "jinja2>=3.1" "fastapi>=0.115" "uvicorn>=0.30" "python-multipart>=0.0.9" "markdown>=3.6" "lark>=1.0" \
      "rapidfuzz>=3" "pillow>=10.4"
COPY src ./src
COPY scripts ./scripts
COPY deploy/serve.py ./serve.py
COPY protocol.yaml config.yaml ./
COPY docs/demo_cases.txt ./docs/demo_cases.txt
ENV PYTHONPATH=/srv/src AUDITPACE_MOCK=1 PROCESSED_DIR=/srv/data/processed PORT=8030
EXPOSE 8030
CMD ["python", "serve.py"]
