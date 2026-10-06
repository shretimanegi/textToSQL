"""Pick the fixed 200-question eval subset (seed 42, stratified by difficulty).

    uv run python -m eval.make_subset      # needs eval/data/gold_status.json from eval.gold

Only questions whose gold SQL runs on Postgres are eligible. Writes eval/subset.json (committed),
so every run, and every feature, is measured on the identical questions.
"""

import json
import random
from collections import defaultdict
from pathlib import Path

SEED = 42
N = 200
SUBSET = Path(__file__).parent / "subset.json"
GOLD_STATUS = Path(__file__).parent / "data" / "gold_status.json"


def pick(eligible: list[dict], n: int = N, seed: int = SEED) -> list[int]:
    """Proportional allocation per difficulty (largest remainder), seeded shuffle within each."""
    by_diff: dict[str, list[int]] = defaultdict(list)
    for r in eligible:
        by_diff[r["difficulty"]].append(r["question_id"])
    total = sum(len(v) for v in by_diff.values())
    quotas = {d: n * len(v) / total for d, v in by_diff.items()}
    alloc = {d: int(q) for d, q in quotas.items()}
    for d in sorted(quotas, key=lambda d: quotas[d] - alloc[d], reverse=True)[: n - sum(alloc.values())]:
        alloc[d] += 1
    rng = random.Random(seed)
    chosen: list[int] = []
    for d in sorted(by_diff):
        ids = sorted(by_diff[d])
        rng.shuffle(ids)
        chosen += ids[: alloc[d]]
    return sorted(chosen)


def main() -> None:
    status = json.loads(GOLD_STATUS.read_text())
    eligible = [r for r in status if r["ok"]]
    ids = pick(eligible)
    SUBSET.write_text(json.dumps({"seed": SEED, "n": len(ids), "eligible": len(eligible),
                                  "total": len(status), "question_ids": ids}, indent=1))
    by_id = {r["question_id"]: r for r in status}
    from collections import Counter
    print(f"wrote {len(ids)} ids; eligible {len(eligible)}/{len(status)}")
    print("difficulty:", dict(Counter(by_id[i]["difficulty"] for i in ids)))
    print("db:", dict(Counter(by_id[i]["db_id"] for i in ids)))


if __name__ == "__main__":
    main()
