#!/usr/bin/env python3
import argparse
from hermes_metrics import load_config, get_model_chain, get_usage_metrics, load_model_limits


def main():
    parser = argparse.ArgumentParser(description="Monitor Hermes model token usage")
    parser.add_argument("--days", type=int, default=None, help="Only show usage from last N days")
    parser.add_argument("--limit", type=int, default=0, help="Default token limit for models without a configured limit")
    args = parser.parse_args()

    config = load_config()
    chain = get_model_chain(config)
    metrics = get_usage_metrics(days=args.days)
    limits = load_model_limits(config)

    default_limit = args.limit

    enriched = []
    for entry in chain:
        model = entry["model"]
        used = metrics.get(model, 0)
        limit = limits.get(model, default_limit)
        left = max(limit - used, 0) if limit else 0
        pct = (used / limit) * 100 if limit > 0 else 0
        enriched.append({**entry, "used": used, "limit": limit, "left": left, "pct": pct})

    enriched.sort(key=lambda m: m["pct"])

    total_used = sum(m["used"] for m in enriched)
    total_limit = sum(m["limit"] for m in enriched) if any(m["limit"] for m in enriched) else 0

    print(f"{'Role':<10} | {'Model':<48} | {'Used':>10} | {'Limit':>10} | {'Left':>10} | {'%':>6}")
    print("-" * 105)

    for m in enriched:
        limit_str = f"{m['limit']:,d}" if m['limit'] else "N/A"
        left_str = f"{m['left']:,d}" if m['limit'] else "N/A"
        pct_str = f"{m['pct']:.1f}%" if m['limit'] else "N/A"
        print(f"{m['role']:<10} | {m['model']:<48} | {m['used']:>10,d} | {limit_str:>10} | {left_str:>10} | {pct_str:>6}")

    print("-" * 105)
    total_line = f"Total Used: {total_used:,d}"
    if total_limit:
        total_line += f"  |  Total Limit: {total_limit:,d}  |  Overall: {(total_used/total_limit)*100:.1f}%"
    print(total_line)


if __name__ == "__main__":
    main()
