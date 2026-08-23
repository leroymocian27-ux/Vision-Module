from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.contracts.integration_v1 import contract_json_schemas


def main() -> int:
    parser = argparse.ArgumentParser(description="Export the versioned integration JSON Schemas.")
    parser.add_argument("--output-dir", default="docs/contracts")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, schema in contract_json_schemas().items():
        (output_dir / f"{name}.schema.json").write_text(
            json.dumps(schema, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
