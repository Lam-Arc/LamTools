from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.app_server.protocol import (  # noqa: E402
    AppendEventInput,
    InitializeParams,
    JsonRpcRequest,
    JsonRpcResponse,
    WriterAppEventEnvelope,
)


MODELS = {
    "JsonRpcRequest": JsonRpcRequest,
    "JsonRpcResponse": JsonRpcResponse,
    "InitializeParams": InitializeParams,
    "WriterAppEventEnvelope": WriterAppEventEnvelope,
    "AppendEventInput": AppendEventInput,
}


def schema_bundle() -> dict[str, Any]:
    return {
        "schema_version": "writer.app_server.schema.v1",
        "source": "members/writer/backend/app/app_server/protocol.py",
        "models": {name: model.model_json_schema() for name, model in MODELS.items()},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True, help="Path to write protocol.schema.json")
    args = parser.parse_args()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(schema_bundle(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
