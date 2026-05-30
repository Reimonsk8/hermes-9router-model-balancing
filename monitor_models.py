#!/usr/bin/env python3
"""
monitor_models.py — Hermes 9Router CLI Usage Viewer

Displays a formatted table of model token usage, limits, health scores,
cost data, and smart scores.

Usage:
    python3 monitor_models.py                                  # all-time usage
    python3 monitor_models.py --days 7                         # last 7 days
    python3 monitor_models.py --days 7 --limit 1000000         # default limit
    python3 monitor_models.py --days 7 --scores                # show smart scores
    python3 monitor_models.py --days 7 --alerts                # show active alerts
    python3 monitor_models.py --days 7 --budget                # show budget details
    python3 monitor_models.py --days 7 --json                  # JSON output
"""

import argparse
import json
import sys
from hermes_metrics import (
    load_config, get_model_chain, get_usage_metrics, load_pricing,
    NineRouter, DEFAULT_CONFIG_PATH, DEFAULT_DB_PATH,
    DEFAULT_PRICING_PATH, DEFAULT_BUDGET_MONTHLY,
)


def main():
    parser = argparse.ArgumentParser(
        description="Monitor Hermes model token usage, scores, and budget"
    )
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH, help="Hermes config path")
    parser.add_argument("--db", default=DEFAULT_DB_PATH, help="Hermes state.db path")
    parser.add_argument("--pricing", default=DEFAULT_PRICING_PATH, help="Pricing database path")
    parser.add_argument("--days", type=int, default=None, help="Only show usage from last N days")
    parser.add_argument("--limit", type=int, default=0, help="Default token limit for unconfigured models")
    parser.add_argument("--budget", type=float, default=DEFAULT_BUDGET_MONTHLY, help="Monthly budget in USD")
    parser.add_argument("--scores", action="store_true", help="Show smart model scores")
    parser.add_argument("--alerts", action="store_true", help="Show active alerts")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    config = load_config(args.config)
    chain = get_model_chain(config)
    metrics = get_usage_metrics(args.db, days=args.days)
    limits = load_pricing(args.pricing)
    configured_limits = config.get("model_limits", {})
    default_limit = args.limit

    # Build enriched entries
    enriched = []
    for entry in chain:
        model = entry["model"]
        used = metrics.get(model, 0)
        limit = configured_limits.get(model, default_limit)
        left = max(limit - used, 0) if limit else 0
        pct = (used / limit) * 100 if limit > 0 else 0
        mp = load_pricing(args.pricing)
        model_price = mp.get("models", {}).get(model, {})
        cost_str = f"${model_price.get('input_per_million', 0)}/${model_price.get('output_per_million', 0)}M"
        tier = model_price.get("tier", "?")
        enriched.append({
            **entry,
            "used": used,
            "limit": limit,
            "left": left,
            "pct": pct,
            "cost": cost_str,
            "tier": tier,
        })

    enriched.sort(key=lambda m: (m["pct"] if m["limit"] else 0, m["used"]), reverse=True)

    # Get smart scores if requested
    scores = None
    if args.scores:
        try:
            nr = NineRouter(
                config_path=args.config,
                hermes_db=args.db,
                pricing_path=args.pricing,
                monthly_budget=args.budget,
                default_limit=default_limit,
            )
            nr.load()
            nr.sync()
            scores = nr.score_models()
        except Exception as e:
            print(f"Warning: Could not compute scores: {e}", file=sys.stderr)

    # Get budget info
    budget_info = None
    if args.budget:
        try:
            nr = NineRouter(
                config_path=args.config,
                hermes_db=args.db,
                pricing_path=args.pricing,
                monthly_budget=args.budget,
                default_limit=default_limit,
            )
            nr.load()
            nr.sync()
            budget_info = nr.get_budget_zone()
        except Exception as e:
            print(f"Warning: Could not get budget info: {e}", file=sys.stderr)

    # Get alerts if requested
    alerts = None
    if args.alerts:
        try:
            nr = NineRouter(
                config_path=args.config,
                hermes_db=args.db,
                pricing_path=args.pricing,
                monthly_budget=args.budget,
                default_limit=default_limit,
            )
            nr.load()
            nr.sync()
            alerts = nr.db.get_active_alerts()
        except Exception as e:
            print(f"Warning: Could not get alerts: {e}", file=sys.stderr)

    if args.json:
        output = {
            "models": enriched,
            "scores": scores,
            "budget": budget_info,
            "alerts": alerts,
        }
        print(json.dumps(output, indent=2, default=str))
        return

    # ── Budget Summary ──
    if budget_info:
        zone_colors = {0: "GREEN", 1: "YELLOW", 2: "ORANGE", 3: "RED"}
        zone = zone_colors.get(budget_info["zone"], "?")
        print(f"\n{' Budget ':─^60}")
        print(f"  Zone:       {zone}")
        print(f"  Spent:      ${budget_info['spend']:.2f} / ${budget_info['budget']:.2f}")
        print(f"  Percent:    {budget_info['percent']:.1f}%")
        print(f"  Remaining:  ${budget_info['remaining']:.2f}")
        print(f"  Daily:      ${budget_info['daily_spend']:.4f}")
        print(f"  Projected:  ${budget_info['projected']:.2f}")
        print("─" * 60)

    # ── Model Usage Table ──
    total_used = sum(m["used"] for m in enriched)
    total_limit = sum(m["limit"] for m in enriched) if any(m["limit"] for m in enriched) else 0

    print(f"\n{' Model Usage ':=^105}")
    print(f"{'Role':<10} | {'Model':<42} | {'Used':>10} | {'Limit':>10} | {'Left':>10} | {'%':>6} | {'Tier':<8} | {'Cost':<18}")
    print("─" * 115)
    for m in enriched:
        limit_str = f"{m['limit']:,d}" if m["limit"] else "N/A"
        left_str = f"{m['left']:,d}" if m["limit"] else "N/A"
        pct_str = f"{m['pct']:.1f}%" if m["limit"] else "N/A"
        print(f"{m['role']:<10} | {m['model']:<42} | {m['used']:>10,d} | {limit_str:>10} | {left_str:>10} | {pct_str:>6} | {m['tier']:<8} | {m['cost']:<18}")
    print("─" * 115)
    total_line = f"Total Used: {total_used:,d}"
    if total_limit:
        total_line += f"  |  Total Limit: {total_limit:,d}  |  Overall: {(total_used/total_limit)*100:.1f}%"
    print(total_line)

    # ── Smart Scores ──
    if scores:
        print(f"\n{' Smart Scores ':=^105}")
        print(f"{'Rank':<6} | {'Model':<42} | {'Score':>6} | {'Quality':>8} | {'Health':>8} | {'Quota':>6} | {'Latency':>8} | {'Cost':>6} | {'Balance':>8}")
        print("─" * 105)
        for i, s in enumerate(scores):
            print(f"{i+1:<6} | {s['model']:<42} | {s['score']:>6.1f} | {s['quality']:>8.0f} | {s['health']:>8.1f} | {s['quota']:>6.0f} | {s['latency']:>8.0f} | {s['cost_score']:>6.0f} | {s['balance']:>8.1f}")
        print("─" * 105)

    # ── Alerts ──
    if alerts:
        print(f"\n{' Active Alerts ':=^60}")
        for a in alerts:
            sev = a["severity"].upper()
            print(f"  [{sev}] {a['message']}")
        print("─" * 60)


if __name__ == "__main__":
    main()
