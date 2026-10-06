"""Ablation configurations. Each adds one feature on top of the previous one."""

CONFIGS = {
    "f1": {"name": "F1 baseline (full schema)", "schema_retrieval": False, "few_shot": False},
    "f2": {"name": "+ F2 schema retrieval", "schema_retrieval": True, "few_shot": False},
    "f3": {"name": "+ F3 few-shot retrieval", "schema_retrieval": True, "few_shot": True},
    # F4 re-runs F3's exact first-attempt prompts (served from the cache) and only pays for the retries.
    "f4": {"name": "+ F4 self-correction", "schema_retrieval": True, "few_shot": True, "self_correction": True,
           "max_retries": 2},
}

DATASET = "bird_dev_200"
EVIDENCE = True          # BIRD's standard setting: the per-question hint goes in the prompt
EXEC_TIMEOUT_S = 30      # eval-only; the product timeout stays 5s

# Estimated paid-tier USD per 1M tokens (input, output). The free tier costs nothing; this is
# only so the ablation table can show a comparable "cost per question". Verify before quoting.
PRICE_PER_M = {"gemini-2.5-flash": (0.30, 2.50)}
