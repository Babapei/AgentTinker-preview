"""Convert validated native reference observations to a bounded portable JSON package."""

import argparse
import json
from pathlib import Path
from tempfile import NamedTemporaryFile

from agenttinker.experiments.reference import package_reference
from agenttinker.packages.models import canonical


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        package = package_reference(json.loads(args.reference.read_text()))
        data = canonical(package)
    except Exception as error:
        print(json.dumps({"converted": False, "error_code": type(error).__name__}))
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=args.output.parent, delete=False) as handle:
        handle.write(data)
        temporary = Path(handle.name)
    temporary.replace(args.output)
    print(json.dumps({"converted": True, "output": str(args.output), "size_bytes": len(data)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
