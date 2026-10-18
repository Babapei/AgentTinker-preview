"""Start the single-owner local runtime; startup does not call a provider."""

import argparse
from pathlib import Path

import uvicorn

from agenttinker.api.app import create_app
from agenttinker.m0.accounting import PriceBook


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--database", type=Path, default=Path("artifacts/runs.sqlite"))
    parser.add_argument("--pricing", type=Path, help="Explicit versioned price-book JSON")
    parser.add_argument(
        "--web-dist",
        type=Path,
        help="Serve a built web directory, e.g. web/dist, on the same address",
    )
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("invalid_port")
    pricing = None
    if args.pricing:
        try:
            pricing = PriceBook.model_validate_json(args.pricing.read_text())
        except (OSError, ValueError):
            parser.error("invalid_pricing_file")
    try:
        app = create_app(args.database, pricing=pricing, web_dist=args.web_dist)
    except ValueError:
        parser.error(
            "web_build_missing: run npm --prefix web run build and pass --web-dist web/dist"
        )
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        workers=1,
        timeout_graceful_shutdown=40,
    )


if __name__ == "__main__":
    main()
