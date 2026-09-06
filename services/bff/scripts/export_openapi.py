"""Export the FastAPI OpenAPI document for web codegen.

FastAPI/Pydantic is the single source of truth for the Lumi API
contract. This script dumps the app's OpenAPI JSON deterministically
(sorted keys, no timestamps) so the committed artifact only changes
when the contract changes, and CI can detect drift.

Usage:

    uv run python scripts/export_openapi.py
"""

import json
import sys
from pathlib import Path

BFF_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BFF_ROOT / "src"))

from lumirss.main import app  # noqa: E402

OUT_PATH = (
    BFF_ROOT.parents[1] / "apps" / "web" / "src" / "api" / "generated" / "openapi.json"
)


def main() -> None:
    schema = app.openapi()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        json.dumps(schema, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    paths = len(schema.get("paths", {}))
    schemas = len(schema.get("components", {}).get("schemas", {}))
    print(
        f"wrote {OUT_PATH.relative_to(BFF_ROOT.parents[1])} "
        f"({paths} paths, {schemas} schemas)"
    )


if __name__ == "__main__":
    main()
