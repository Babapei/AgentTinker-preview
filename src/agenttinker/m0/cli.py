"""Generate M0 evidence without silently substituting a synthetic model."""

import argparse
import json
from pathlib import Path
from tempfile import NamedTemporaryFile

from agenttinker.m0.accounting import PriceBook
from agenttinker.m0.deepseek_model import DeepSeekModel
from agenttinker.m0.openai_model import OpenAIModel, ProviderNotConfigured
from agenttinker.m0.probe import ProbeFailed, run_comparison
from agenttinker.m0.synthetic import SyntheticModel


def write_report(output: Path, report: dict) -> None:
    """Replace only after full serialization and writing have succeeded."""
    payload = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=output.parent, prefix=f".{output.name}.", delete=False
    )
    path = Path(temporary.name)
    try:
        with temporary:
            temporary.write(payload)
        path.replace(output)
    finally:
        path.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["synthetic", "live"], required=True)
    parser.add_argument("--provider", choices=["openai", "deepseek"], help="Live provider profile")
    parser.add_argument("--model", help="Explicit model ID; or set the provider's *_MODEL variable")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--pricing", type=Path, help="Explicit versioned price-book JSON")
    args = parser.parse_args()
    output = args.output or Path(f"artifacts/m0-{args.mode}.json")
    if args.mode == "synthetic" and (args.model or args.provider):
        parser.error("--model and --provider are only supported with --mode live")
    profile = DeepSeekModel if args.provider == "deepseek" else OpenAIModel
    pricing = None
    if args.pricing:
        try:
            pricing = PriceBook.model_validate_json(args.pricing.read_text())
        except (OSError, ValueError):
            parser.error("invalid_pricing_file: a valid versioned price-book JSON is required")
    try:
        model = (
            SyntheticModel() if args.mode == "synthetic" else profile.from_environment(args.model)
        )
    except ProviderNotConfigured as error:
        parser.error(str(error))
    try:
        report = run_comparison(model, pricing=pricing)
    except ProbeFailed as error:
        failed_output = output.with_name(f"{output.stem}.failed.json")
        try:
            write_report(failed_output, error.report)
        except (OSError, ValueError):
            parser.exit(1, "probe_failed: diagnostic_write_failed; success report was preserved\n")
        parser.exit(
            1, f"probe_failed: {error.report['error']['code']}; diagnostic: {failed_output}\n"
        )
    finally:
        if isinstance(model, OpenAIModel):
            model.close()
    try:
        write_report(output, report)
    except (OSError, ValueError):
        parser.exit(1, "report_write_failed: no new success report was written\n")
    print(json.dumps({"mode": report["mode"], "checks": report["checks"], "output": str(output)}))


if __name__ == "__main__":
    main()
