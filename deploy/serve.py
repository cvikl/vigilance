"""Container entry point: the workbench only (no OCR, no browser, no model calls).

Builds the FastAPI app the same way `auditpace workbench` does, without importing the CLI, so the
image needs none of the S3/S4 native dependencies (tesserocr, playwright)."""
import os
from pathlib import Path

import uvicorn

from auditpace.protocol import load_protocol, require_locked
from auditpace.workbench.app import create_app
from auditpace.workbench.demo import read_held

protocol = load_protocol(Path(os.environ.get("PROTOCOL", "protocol.yaml")))
require_locked(protocol)
app = create_app(Path(os.environ.get("PROCESSED_DIR", "data/processed")), protocol, held=read_held())
uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8030")), log_level="warning",
            proxy_headers=True, forwarded_allow_ips="*")
