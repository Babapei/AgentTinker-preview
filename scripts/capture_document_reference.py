"""Capture one native document A/B; explicit live mode can incur provider fees."""

import argparse
import json
from pathlib import Path
from tempfile import NamedTemporaryFile

from agenttinker.experiments.reference import capture_document
from agenttinker.runtime.service import DocumentRunRequest
from agenttinker.storage.sqlite import SQLiteEventStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", required=True, choices=("synthetic", "live"))
    parser.add_argument("--provider", choices=("deepseek", "openai"))
    parser.add_argument("--model")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        request = DocumentRunRequest(mode=args.mode, provider=args.provider, model=args.model)
        report = capture_document(args.database, request)
    except Exception as error:
        report = {
            "schema_version": "m4-document-reference-1",
            "mode": args.mode,
            "real_reference_verified": False,
            "checks": {"capture_completed": False},
            "error_code": type(error).__name__,
            "runs": {},
            "events": {},
        }
        if args.database.exists():
            with SQLiteEventStore(args.database) as store:
                for run_id in store.run_ids():
                    report["runs"][run_id] = store.get_view(run_id).model_dump(mode="json")
                    report["events"][run_id] = [
                        e.model_dump(mode="json") for e in store.events(run_id)
                    ]
    verified = bool(report["checks"]) and all(report["checks"].values())
    output = args.output if verified else args.output.with_suffix(".failed.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(mode="w", dir=output.parent, delete=False) as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(output)
    print(
        json.dumps(
            {
                "mode": args.mode,
                "verified": verified,
                "real_reference_verified": report["real_reference_verified"],
                "measurements": report.get("measurements"),
                "output": str(output),
            }
        )
    )
    return 0 if verified else 1


if __name__ == "__main__":
    raise SystemExit(main())
