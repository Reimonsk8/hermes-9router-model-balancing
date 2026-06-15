#!/usr/bin/env python3
"""
monitor_models.py — Hermes model usage viewer with progress bars.

Reads from Hermes state.db by default. Use --nine-router to read real cost
and usage data from the 9Router SQLite database.

Usage:
    python3 monitor_models.py
    python3 monitor_models.py --days 7
    python3 monitor_models.py --nine-router
    python3 monitor_models.py --nine-router --days 7
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
from datetime import datetime, timezone, timedelta
from typing import Optional

from hermes_metrics import (
    load_config, load_pricing, NineRouter,
    DEFAULT_CONFIG_PATH, DEFAULT_DB_PATH,
    DEFAULT_PRICING_PATH, DEFAULT_BUDGET_MONTHLY,
)

DEFAULT_9ROUTER_DB = "/root/.9router/db/data.sqlite"

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


def get_9router_models(db_path: str, days: Optional[int] = None) -> list[dict]:
    if not os.path.exists(db_path):
        print(f"9Router DB not found: {db_path}", file=sys.stderr)
        return []

    conn = sqlite3.connect(db_path)
    rows = []
    try:
        cursor = conn.cursor()
        if days:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
            params = [cutoff]
            where = "WHERE status = 'ok' AND model IS NOT NULL AND model != '' AND timestamp >= ?"
        else:
            params = []
            where = "WHERE status = 'ok' AND model IS NOT NULL AND model != ''"

        cursor.execute(f"""
            SELECT
                model,
                COUNT(*) as requests,
                COALESCE(SUM(promptTokens), 0) as input_tokens,
                COALESCE(SUM(completionTokens), 0) as output_tokens,
                COALESCE(SUM(cost), 0.0) as total_cost
            FROM usageHistory
            {where}
            GROUP BY model
            ORDER BY requests DESC
        """, params)

        for row in cursor.fetchall():
            rows.append({
                "model": row[0],
                "tokens": row[2] + row[3],
                "input_tokens": row[2],
                "output_tokens": row[3],
                "sessions": row[1],
                "total_cost": row[4],
                "api_calls": row[1],
                "reasoning_tokens": 0,
            })
    except sqlite3.Error as e:
        print(f"9Router DB error: {e}", file=sys.stderr)
    finally:
        conn.close()
    return rows


def get_9router_summary(db_path: str) -> dict:
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                COUNT(*) as requests,
                COALESCE(SUM(promptTokens), 0) as input_tokens,
                COALESCE(SUM(completionTokens), 0) as output_tokens,
                COALESCE(SUM(cost), 0.0) as cost
            FROM usageHistory
            WHERE status = 'ok'
        """)
        row = cursor.fetchone()
        return {
            "requests": row[0],
            "input_tokens": row[1],
            "output_tokens": row[2],
            "cost": row[3],
        }
    finally:
        conn.close()


def get_9router_recent(db_path: str, limit: int = 20) -> list[dict]:
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, timestamp, provider, model, promptTokens, completionTokens, cost
            FROM usageHistory
            WHERE status = 'ok'
            ORDER BY id DESC LIMIT ?
        """, (limit,))
        return [{
            "id": r[0],
            "ts": r[1],
            "provider": r[2] or "",
            "model": r[3] or "",
            "input": r[4] or 0,
            "output": r[5] or 0,
            "cost": r[6] or 0.0,
        } for r in cursor.fetchall()]
    finally:
        conn.close()


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


def fmt_ago(ts_str: str) -> str:
    try:
        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        delta = datetime.now(timezone.utc) - ts
        if delta.total_seconds() < 60:
            return f"{int(delta.total_seconds())}s ago"
        elif delta.total_seconds() < 3600:
            return f"{int(delta.total_seconds() / 60)}m ago"
        elif delta.total_seconds() < 86400:
            return f"{int(delta.total_seconds() / 3600)}h ago"
        else:
            return f"{int(delta.total_seconds() / 86400)}d ago"
    except:
        return ts_str


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
    parser.add_argument("--9router-db", dest="nr_db", default=DEFAULT_9ROUTER_DB)
    parser.add_argument("--days", type=int, default=None)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--budget", type=float, default=DEFAULT_BUDGET_MONTHLY)
    parser.add_argument("--scores", action="store_true")
    parser.add_argument("--alerts", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--nine-router", dest="nr_mode", action="store_true", help="Read real usage/cost from 9Router DB")
    args = parser.parse_args()

    if args.nr_mode:
        summary = get_9router_summary(args.nr_db)
        if not summary:
            print("No data in 9Router DB.", file=sys.stderr)
            return

        models_data = get_9router_models(args.nr_db, days=args.days)
        recent = get_9router_recent(args.nr_db)

        config = load_config(args.config)
        pricing = load_pricing(args.pricing)
        pricing_models = pricing.get("models", {})
        configured_limits = config.get("model_limits", {})
        default_limit = args.limit

        for m in models_data:
            pm = pricing_models.get(m["model"], {})
            limit = configured_limits.get(
                m["model"],
                DEFAULT_MODEL_LIMITS.get(m["model"], pm.get("token_limit", default_limit))
            )
            m["limit"] = limit
            m["pct"] = (m["tokens"] / m["limit"]) * 100 if m["limit"] else 0
            m["tier"] = pm.get("tier", "?")
            provider = m["model"].split("/")[0] if "/" in m["model"] else m["model"]
            m["health"] = pm.get("health_score", pricing.get("provider_default_health", {}).get(provider, 95))
            m["latency"] = pm.get("latency_ms", pricing.get("provider_default_latency", {}).get(provider, 1000))

        if args.json:
            output = {
                "summary": summary,
                "models": models_data,
                "recent": recent,
            }
            print(json.dumps(output, indent=2, default=str))
            return

        total_tokens = sum(m["tokens"] for m in models_data)
        total_sessions = sum(m["sessions"] for m in models_data)

        print(f"\n{' 9Router Analytics (real data) ':=^90}")
        print(f"  Total Requests: {summary['requests']}")
        print(f"  Total Input:    {format_tokens(summary['input_tokens'])} tokens")
        print(f"  Total Output:   {format_tokens(summary['output_tokens'])} tokens")
        print(f"  Est. Cost:      ${summary['cost']:.4f}")
        print("=" * 90)

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

            line = (
                f"\u2695 {name:<30}"
                f" | {used_str:>7}/{limit_str:<7}"
                f" | {bar:>12}"
                f" | {pct_str:>6}"
                f" | {time_est:>10}"
                f" | \u23f1 {m['latency']:.0f}ms"
                f" | cost=${m['total_cost']:.4f}"
                f" | tier={m['tier']}"
                f" | health={m['health']:.0f}%"
                f" | req={m['sessions']}"
            )
            print(line)

        print("=" * 90)
        print(f"  Total: {format_tokens(total_tokens)} tokens, {total_sessions} requests")

        print(f"\n{' Recent Requests ':=^90}")
        print(f"  {'Model':<35} {'In':>8} / {'Out':<6} {'Cost':>10} {'When':<12}")
        print("  " + "-" * 75)
        for r in recent:
            mname = short_model(r["model"])
            cost_str = f"${r['cost']:.4f}" if r['cost'] > 0 else "$0"
            print(f"  {mname:<35} {r['input']:>8} / {r['output']:<6} {cost_str:>10} {fmt_ago(r['ts']):<12}")
        print("-" * 90)

        return

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

    print(f"\n{' Model Usage (Hermes state.db) ':=^90}")
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
