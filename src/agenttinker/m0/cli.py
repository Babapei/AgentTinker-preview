"""Generate M0 evidence without silently substituting a synthetic model."""

import argparse
import json
from pathlib import Path

from openai import OpenAIError

from agenttinker.m0.accounting import PriceBook
from agenttinker.m0.deepseek_model import DeepSeekModel
from agenttinker.m0.openai_model import OpenAIModel, ProviderNotConfigured
from agenttinker.m0.probe import run_comparison
from agenttinker.m0.synthetic import SyntheticModel


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["synthetic", "live"], required=True)
    parser.add_argument("--provider", choices=["openai", "deepseek"], help="Live provider profile")
    parser.add_argument("--model", help="Explicit model ID; alternatively set OPENAI_MODEL")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--pricing", type=Path, help="Explicit versioned price-book JSON")
    args = parser.parse_args()
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
    except OpenAIError as error:
        parser.exit(1, f"provider_call_failed: {type(error).__name__}; no new report was written\n")
    except (ValueError, RuntimeError) as error:
        parser.exit(1, f"probe_failed: {type(error).__name__}; no new report was written\n")
    finally:
        if isinstance(model, OpenAIModel):
            model.close()
    output = args.output or Path(f"artifacts/m0-{args.mode}.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"mode": report["mode"], "checks": report["checks"], "output": str(output)}))


if __name__ == "__main__":
    main()
