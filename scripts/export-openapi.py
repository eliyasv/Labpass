"""Export the API contract without connecting to a database or reading secrets."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from labpass.app import create_app
from labpass.config import Settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    app = create_app(Settings("postgresql+psycopg://schema_only@127.0.0.1/schema_only"))
    # The engine is lazy; exporting OpenAPI performs no database operation.
    content = json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"
    if args.check:
        if not args.path.exists() or args.path.read_text() != content:
            raise SystemExit(
                "API contract changed: export OpenAPI and run npm run generate."
            )
        print("Backend OpenAPI matches frontend contract")
    else:
        args.path.write_text(content)
        print(f"Wrote API contract to {args.path}")


if __name__ == "__main__":
    main()
