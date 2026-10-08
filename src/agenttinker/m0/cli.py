"""Generate M0 evidence without silently substituting a synthetic model."""

import argparse
import json
from pathlib import Path

from openai import OpenAIError

from agenttinker.m0.openai_model import OpenAIModel, ProviderNotConfigured
from agenttinker.m0.probe import run_comparison
from agenttinker.m0.synthetic import SyntheticModel


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["synthetic", "live"], required=True)
    parser.add_argument("--model", help="Explicit model ID; alternatively set OPENAI_MODEL")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.mode == "synthetic" and args.model:
        parser.error("--model is only supported with --mode live")
    try:
        model = (
            SyntheticModel()
            if args.mode == "synthetic"
            else OpenAIModel.from_environment(args.model)
        )
    except ProviderNotConfigured as error:
        parser.error(str(error))
    try:
        report = run_comparison(model)
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
