from __future__ import annotations

import multiprocessing
import os

import uvicorn

from app.main import app


def main() -> None:
    host = os.environ.get("LAMWRITER_HOST", "127.0.0.1")
    port = int(os.environ.get("LAMWRITER_PORT", "6173"))
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    if os.name == "nt":
        multiprocessing.freeze_support()
    main()
