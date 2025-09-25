"""Pricing validation utility.

Purpose:
  Warn (and optionally fail) when any model in the legacy pricing dict or the
  extended MODEL_METADATA has zero (placeholder) pricing values. This helps
  ensure production cost calculations aren't silently under-reporting.

Behavior:
  - Prints a table of models with zero Input or Output pricing.
  - Non‑zero pricing models are ignored unless --all is passed.
  - Exit codes:
        0 = No zero-priced models OR zero-priced allowed (non-production)
        2 = Zero-priced models detected and treated as error (production mode)

Usage:
  python -m helpers.validate_pricing                # warnings only
  python -m helpers.validate_pricing --fail-on-zero # force non-zero exit if any placeholder
  PRODUCTION=1 python -m helpers.validate_pricing   # auto fail on zero pricing
  python helpers/validate_pricing.py --all          # show every model

Integration:
  Add to CI prior to deployment. Example (bash):
     PRODUCTION=1 python -m helpers.validate_pricing --fail-on-zero

Notes:
  Placeholder detection = (price == 0). Update values in completion_pricing.py
  once authoritative Sweden Central EUR pricing is available.
"""

from __future__ import annotations

import os
import argparse
from typing import List, Tuple

from .completion_pricing import model_pricing_euros, MODEL_METADATA


def collect_zero_priced() -> List[Tuple[str, str, float, float]]:
    rows = []
    # Legacy dict
    for model, data in model_pricing_euros.items():
        if data.get("Input", 0) == 0 or data.get("Output", 0) == 0:
            rows.append((model, "legacy", data.get("Input", 0), data.get("Output", 0)))
    # Metadata mapping
    for model, meta in MODEL_METADATA.items():
        ic = meta.get("input_cost_per_1k", 0)
        oc = meta.get("output_cost_per_1k", 0)
        if ic == 0 or oc == 0:
            rows.append((model, "metadata", ic, oc))
    # Deduplicate (prefer metadata classification if duplicate)
    dedup = {}
    for m, kind, i, o in rows:
        dedup[m] = (kind, i, o)
    return [(m, k, i, o) for m, (k, i, o) in sorted(dedup.items())]


def collect_all() -> List[Tuple[str, str, float, float]]:
    rows = []
    for model, data in model_pricing_euros.items():
        rows.append((model, "legacy", data.get("Input", 0.0), data.get("Output", 0.0)))
    for model, meta in MODEL_METADATA.items():
        rows.append((model, "metadata", meta.get("input_cost_per_1k", 0.0), meta.get("output_cost_per_1k", 0.0)))
    # Deduplicate (metadata last wins)
    dedup = {}
    for m, kind, i, o in rows:
        dedup[m] = (kind, i, o)
    return [(m, k, i, o) for m, (k, i, o) in sorted(dedup.items())]


def format_table(rows: List[Tuple[str, str, float, float]]) -> str:
    if not rows:
        return "(none)"
    name_w = max(len(r[0]) for r in rows)
    kind_w = max(len(r[1]) for r in rows)
    header = f"{'MODEL'.ljust(name_w)}  {'SRC'.ljust(kind_w)}  INPUT_EUR/1K  OUTPUT_EUR/1K"
    sep = "-" * len(header)
    lines = [header, sep]
    for model, kind, ic, oc in rows:
        lines.append(f"{model.ljust(name_w)}  {kind.ljust(kind_w)}  {ic:12.6f}  {oc:13.6f}")
    return "\n".join(lines)


def main():  # pragma: no cover (CLI utility)
    parser = argparse.ArgumentParser(description="Validate model pricing metadata.")
    parser.add_argument("--fail-on-zero", action="store_true", help="Exit with code 2 if zero-priced models exist.")
    parser.add_argument("--all", action="store_true", help="List all models, not only zero-priced.")
    args = parser.parse_args()

    production = os.getenv("PRODUCTION") in ("1", "true", "True")

    if args.all:
        rows = collect_all()
        print("All model pricing entries:\n" + format_table(rows))
        zero_rows = collect_zero_priced()
        if zero_rows:
            print("\nZero-priced subset:\n" + format_table(zero_rows))
    else:
        zero_rows = collect_zero_priced()
        if zero_rows:
            print("Zero-priced model entries detected (placeholders):\n" + format_table(zero_rows))
        else:
            print("No zero-priced placeholder models detected.")

    should_fail = (args.fail_on_zero or production) and bool(collect_zero_priced())
    if should_fail:
        print("\nFAIL: Zero-priced models present. Update pricing before production deploy.")
        raise SystemExit(2)

    print("\nValidation complete.")


if __name__ == "__main__":  # pragma: no cover
    main()
