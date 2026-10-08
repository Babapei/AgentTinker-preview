"""Generate M0 evidence without silently substituting a synthetic model."""

import argparse
import json
from pathlib import Path

from agenttinker.m0.probe import run_comparison
from agenttinker.m0.synthetic import SyntheticModel


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["synthetic"], required=True)
    parser.add_argument("--output", type=Path, default=Path("artifacts/m0-synthetic.json"))
    args = parser.parse_args()
    report = run_comparison(SyntheticModel())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps({"mode": report["mode"], "checks": report["checks"], "output": str(args.output)})
    )


if __name__ == "__main__":
    main()
