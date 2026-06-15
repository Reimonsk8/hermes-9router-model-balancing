#!/usr/bin/env python3
"""
monitor_models.py — Hermes model usage viewer with progress bars.

Usage:
    python3 monitor_models.py
    python3 monitor_models.py --days 7
    python3 monitor_models.py --days 7 --scores
    python3 monitor_models.py --days 7 --budget
    python3 monitor_models.py --days 7 --alerts
    python3 monitor_models.py --days 7 --json
"""

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta
from typing import Optional

from hermes_metrics import (
    load_config, load_pricing, NineRouter,
    DEFAULT_CONFIG_PATH, DEFAULT_DB_PATH,
    DEFAULT_PRICING_PATH, DEFAULT_BUDGET_MONTHLY,
)

# Default token limits per model (when not in config/pricing)
DEFAULT_MODEL_LIMITS = {
    "gemini/gemini-3-flash-preview": 1048576,
    "gemini/gemini-2.0-flash-lite": 1048576,
    "gemini/gemini-3.1-flash-lite-preview": 1048576,
    "gemini/gemini-3.1-pro-preview": 2097152,
    "gemini/gemma-4-31b-it": 1048576,
    "cerebras/qwen-3-32b": 131072,
    "cerebras/gpt-oss-120b": 262144,
    "cerebras/llama-3.3-70b": 131072,
    "cerebras/llama-4-scout-17b-16e-instruct": 131072,
    "groq/qwen/qwen3-32b": 131072,
    "groq/llama-3.3-70b-versatile": 131072,
    "groq/openai/gpt-oss-120b": 262144,
    "groq/meta-llama/llama-4-maverick-17b-128e-instruct": 131072,
    "ds/deepseek-chat": 131072,
    "ds/deepseek-v4-flash": 262144,
    "ds/deepseek-v4-pro-max": 262144,
    "nvidia/minimaxai/minimax-m2.7": 131072,
    "stepfun/step-3.5-flash": 131072,
}


def get_session_models(db_path: str, days: Optional[int] = None) -> list[dict]:
    if not os.path.exists(db_path):
        return []
    conn = sqlite3.connect(db_path)
    rows = []
    try:
        cursor = conn.cursor()
        if days:
            cutoff = (datetime.now() - timedelta(days=days)).isoformat()
            params = [cutoff]
            where = "WHERE started_at >= ? AND model IS NOT NULL AND model != ''"
        else:
            params = []
            where = "WHERE model IS NOT NULL AND model != ''"

        cursor.execute(f"""
            SELECT
                model,
                COALESCE(SUM(input_tokens + output_tokens + reasoning_tokens), 0) as total_tokens,
                COALESCE(SUM(input_tokens), 0) as inp,
                COALESCE(SUM(output_tokens), 0) as out,
                COALESCE(SUM(reasoning_tokens), 0) as reason,
                COUNT(*) as session_count,
                AVG(estimated_cost_usd) as avg_cost_per_session,
                COALESCE(SUM(estimated_cost_usd), 0.0) as total_cost,
                COUNT(CASE WHEN api_call_count > 0 THEN 1 END) as api_calls
            FROM sessions
            {where}
            GROUP BY model
            ORDER BY total_tokens DESC
        """, params)

        for row in cursor.fetchall():
            if row[0] is None:
                continue
            rows.append({
                "model": row[0],
                "tokens": row[1],
                "input_tokens": row[2],
                "output_tokens": row[3],
                "reasoning_tokens": row[4],
                "sessions": row[5],
                "avg_cost_per_session": row[6] or 0.0,
                "total_cost": row[7],
                "api_calls": row[8],
            })
    except sqlite3.Error as e:
        print(f"DB error: {e}", file=sys.stderr)
    finally:
        conn.close()
    return rows


def format_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    elif n >= 1_000:
        return f"{n/1_000:.1f}K"
    return str(n)


def fmt_time(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f}s"
    elif seconds < 3600:
        return f"{seconds/60:.0f}m"
    elif seconds < 86400:
        return f"{seconds/3600:.0f}h"
    return f"{seconds/86400:.0f}d"


def progress_bar(pct: float, width: int = 10) -> str:
    filled = round(pct / 100 * width)
    filled = max(0, min(filled, width))
    bar = "█" * filled + "░" * (width - filled)
    return f"[{bar}]"


def short_model(name: str) -> str:
    parts = name.split("/")
    return parts[-1] if len(parts) > 1 else name


def main():
    parser = argparse.ArgumentParser(
        description="Monitor Hermes model token usage, scores, and budget"
    )
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    parser.add_argument("--pricing", default=DEFAULT_PRICING_PATH)
    parser.add_argument("--days", type=int, default=None)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--budget", type=float, default=DEFAULT_BUDGET_MONTHLY)
    parser.add_argument("--scores", action="store_true")
    parser.add_argument("--alerts", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    config = load_config(args.config)
    pricing = load_pricing(args.pricing)
    models_data = get_session_models(args.db, days=args.days)
    configured_limits = config.get("model_limits", {})
    default_limit = args.limit
    pricing_models = pricing.get("models", {})

    for m in models_data:
        pm = pricing_models.get(m["model"], {})
        limit = configured_limits.get(
            m["model"],
            DEFAULT_MODEL_LIMITS.get(m["model"], pm.get("token_limit", default_limit))
        )
        m["limit"] = limit
        m["pct"] = (m["tokens"] / m["limit"]) * 100 if m["limit"] else 0
        m["tier"] = pm.get("tier", "?")
        inp_price = pm.get("input_per_million", 0)
        out_price = pm.get("output_per_million", 0)
        m["cost_str"] = f"${inp_price}/${out_price}M"
        provider = m["model"].split("/")[0] if "/" in m["model"] else m["model"]
        health = pm.get(
            "health_score",
            pricing.get("provider_default_health", {}).get(provider, 95)
        )
        m["health"] = health
        latency = pm.get(
            "latency_ms",
            pricing.get("provider_default_latency", {}).get(provider, 1000)
        )
        m["latency"] = latency

    scores_map = {}
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
            for s in nr.score_models():
                scores_map[s["model"]] = s
        except Exception as e:
            print(f"Warning: Could not compute scores: {e}", file=sys.stderr)

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
            "models": models_data,
            "scores": list(scores_map.values()) or None,
            "budget": budget_info,
            "alerts": alerts,
        }
        print(json.dumps(output, indent=2, default=str))
        return

    if budget_info:
        zone_colors = {0: "GREEN", 1: "YELLOW", 2: "ORANGE", 3: "RED"}
        zone = zone_colors.get(budget_info["zone"], "?")
        print(f"\n{' Budget ':-^50}")
        print(f"  Zone:       {zone}")
        print(f"  Spent:      ${budget_info['spend']:.2f} / ${budget_info['budget']:.2f}")
        print(f"  Percent:    {budget_info['percent']:.1f}%")
        print(f"  Remaining:  ${budget_info['remaining']:.2f}")
        print(f"  Daily:      ${budget_info['daily_spend']:.4f}")
        print(f"  Projected:  ${budget_info['projected']:.2f}")
        print("-" * 50)

    total_tokens = sum(m["tokens"] for m in models_data)
    total_sessions = sum(m["sessions"] for m in models_data)

    print(f"\n{' Model Usage ':=^90}")
    for m in models_data:
        name = short_model(m["model"])
        used_str = format_tokens(m["tokens"])
        limit_val = m["limit"]
        limit_str = format_tokens(limit_val) if limit_val else "N/A"
        pct = m["pct"]
        bar = progress_bar(pct, 10) if limit_val else "[---N/A---]"
        pct_str = f"{pct:.1f}%" if limit_val else "--.-%"

        time_est = ""
        if limit_val and pct > 0:
            used = m["tokens"]
            left = limit_val - used
            if left > 0:
                est = (left / used) * 3600
                time_est = f"{' '}{fmt_time(est)}"
            else:
                time_est = " exhausted"

        health_val = m.get("health", 95)
        latency_val = m.get("latency", 1000)

        line = (
            f"\u2695 {name:<30}"
            f" | {used_str:>7}/{limit_str:<7}"
            f" | {bar:>12}"
            f" | {pct_str:>6}"
            f" | {time_est:>10}"
            f" | \u23f1 {latency_val:.0f}ms"
            f" | cost={m['total_cost']:.2f}"
            f" | tier={m['tier']}"
            f" | health={health_val:.0f}%"
            f" | sessions={m['sessions']}"
        )
        print(line)

    print("=" * 90)
    print(f"  Total: {format_tokens(total_tokens)} tokens, {total_sessions} sessions")

    if scores_map:
        print(f"\n{' Smart Scores ':=^80}")
        items = sorted(scores_map.items(), key=lambda x: x[1]["score"], reverse=True)
        for i, (model, s) in enumerate(items):
            print(f"  {i+1}. {short_model(model):<30} score={s['score']:.1f} "
                  f"quality={s['quality']:.0f} health={s['health']:.1f}% "
                  f"latency={s['latency']:.0f}ms cost={s['cost_score']:.0f}")
        print("-" * 80)

    if alerts:
        print(f"\n{' Active Alerts ':-^50}")
        for a in alerts:
            print(f"  [{a['severity'].upper()}] {a['message']}")
        print("-" * 50)


if __name__ == "__main__":
    main()
