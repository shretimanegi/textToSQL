"""One command runs the benchmark:  uv run python -m eval.run_eval --config f1"""

import argparse
import asyncio
import json

from app.db import close_pools, open_pools
from eval import configs, harness


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True, choices=list(configs.CONFIGS))
    ap.add_argument("--limit", type=int, default=None, help="smoke test on the first N questions (not recorded)")
    ap.add_argument("--concurrency", type=int, default=4)
    args = ap.parse_args()
    await open_pools()
    try:
        out = await harness.run(args.config, args.limit, args.concurrency)
    finally:
        await close_pools()
    print(json.dumps(out["summary"], indent=2))
    print("details:", out["path"])


if __name__ == "__main__":
    asyncio.run(main())
