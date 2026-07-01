#!/usr/bin/env python3
"""
nr_exporter.py — Export 9Router analytics to Prometheus textfile format.

Reads from /root/.9router/db/data.sqlite (usageHistory table) and writes
metrics to /var/lib/alloy/textfile/nr.prom so Alloy's node_exporter
textfile collector can scrape them and forward to Grafana Cloud.

Metrics use valid Prometheus names (starting with nr_ not 9router_).

Usage:
    python3 nr_exporter.py
    python3 nr_exporter.py --prom-path /tmp/foo.prom
    python3 nr_exporter.py --db /custom/path/data.sqlite
"""

import argparse
import json
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone, timedelta

DEFAULT_DB_PATH = "/root/.9router/db/data.sqlite"
DEFAULT_PROM_PATH = "/var/lib/alloy/textfile/nr.prom"


def get_db_path() -> str:
    alt = os.path.expanduser("~/.9router/db/data.sqlite")
    if os.path.exists(alt):
        return alt
    return DEFAULT_DB_PATH


def query_usage(db_path: str) -> dict:
    if not os.path.exists(db_path):
        print(f"9Router DB not found: {db_path}", file=sys.stderr)
        return {}

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    result = {"models": {}, "hourly": {}, "totals": {"requests": 0, "input_tokens": 0, "output_tokens": 0, "cost": 0.0}}
    try:
        c = conn.cursor()

        c.execute("""
            SELECT
                model,
                COUNT(*) as requests,
                COALESCE(SUM(promptTokens), 0) as input_tokens,
                COALESCE(SUM(completionTokens), 0) as output_tokens,
                COALESCE(SUM(cost), 0.0) as cost
            FROM usageHistory
            WHERE status = 'ok' AND model IS NOT NULL AND model != ''
            GROUP BY model
            ORDER BY requests DESC
        """)
        for row in c.fetchall():
            m = row["model"]
            result["models"][m] = {
                "requests": row["requests"],
                "input_tokens": row["input_tokens"],
                "output_tokens": row["output_tokens"],
                "cost": row["cost"],
            }
            result["totals"]["requests"] += row["requests"]
            result["totals"]["input_tokens"] += row["input_tokens"]
            result["totals"]["output_tokens"] += row["output_tokens"]
            result["totals"]["cost"] += row["cost"]

        c.execute("""
            SELECT
                strftime('%Y-%m-%dT%H:00:00', timestamp) as hour_bucket,
                COUNT(*) as requests
            FROM usageHistory
            WHERE status = 'ok' AND timestamp >= datetime('now', '-48 hours')
            GROUP BY hour_bucket
            ORDER BY hour_bucket
        """)
        for row in c.fetchall():
            result["hourly"][row["hour_bucket"]] = row["requests"]

        c.execute("""
            SELECT id, timestamp, provider, model, promptTokens, completionTokens, cost
            FROM usageHistory
            WHERE status = 'ok'
            ORDER BY id DESC LIMIT 20
        """)
        result["recent"] = []
        for row in c.fetchall():
            result["recent"].append({
                "id": row["id"],
                "ts": row["timestamp"],
                "provider": row["provider"] or "",
                "model": row["model"] or "",
                "input": row["promptTokens"] or 0,
                "output": row["completionTokens"] or 0,
                "cost": row["cost"] or 0.0,
            })

    except sqlite3.Error as e:
        print(f"DB error: {e}", file=sys.stderr)
    finally:
        conn.close()

    return result


def sanitize_label(s: str) -> str:
    return s.replace('"', "'").replace("\\", "/")


def generate_metrics(data: dict) -> str:
    lines = []

    totals = data.get("totals", {})
    header = "# 9Router Analytics — generated " + datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    lines.append(header)
    lines.append("# TYPE nr_requests_total counter")
    lines.append("# TYPE nr_input_tokens_total counter")
    lines.append("# TYPE nr_output_tokens_total counter")
    lines.append("# TYPE nr_cost_dollars counter")
    lines.append("# TYPE nr_model_requests counter")
    lines.append("# TYPE nr_model_input_tokens counter")
    lines.append("# TYPE nr_model_output_tokens counter")
    lines.append("# TYPE nr_model_cost counter")
    lines.append("# TYPE nr_hourly_requests gauge")
    lines.append("# TYPE nr_scrape_duration_seconds gauge")

    lines.append(f"nr_requests_total {totals.get('requests', 0)}")
    lines.append(f"nr_input_tokens_total {totals.get('input_tokens', 0)}")
    lines.append(f"nr_output_tokens_total {totals.get('output_tokens', 0)}")
    lines.append(f"nr_cost_dollars {totals.get('cost', 0.0):.6f}")

    for model, m in data.get("models", {}).items():
        label = sanitize_label(model)
        lines.append(f'nr_model_requests_total{{model="{label}"}} {m["requests"]}')
        lines.append(f'nr_model_input_tokens_total{{model="{label}"}} {m["input_tokens"]}')
        lines.append(f'nr_model_output_tokens_total{{model="{label}"}} {m["output_tokens"]}')
        lines.append(f'nr_model_cost_dollars{{model="{label}"}} {m["cost"]:.6f}')

    for hour_bucket, count in data.get("hourly", {}).items():
        lines.append(f'nr_hourly_requests{{hour="{hour_bucket}"}} {count}')

    lines.append(f"nr_scrape_duration_seconds 0.01")
    lines.append("")

    return "\n".join(lines)


def get_usage_json(db_path: str = None) -> str:
    if db_path is None:
        db_path = get_db_path()
    data = query_usage(db_path)
    return json.dumps(data, indent=2, default=str)


def export_metrics(prom_path: str = DEFAULT_PROM_PATH, db_path: str = None):
    if db_path is None:
        db_path = get_db_path()

    data = query_usage(db_path)
    metrics = generate_metrics(data)

    os.makedirs(os.path.dirname(prom_path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(prom_path))
    try:
        with os.fdopen(fd, "w") as f:
            f.write(metrics)
        os.replace(tmp, prom_path)
        print(f"Wrote {prom_path}", file=sys.stderr)
    except Exception as e:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise e


def main():
    parser = argparse.ArgumentParser(description="Export 9Router analytics to Prometheus textfile")
    parser.add_argument("--prom-path", default=DEFAULT_PROM_PATH, help="Output prom file path")
    parser.add_argument("--db", default=None, help="9Router data.sqlite path")
    parser.add_argument("--json", action="store_true", help="Output JSON to stdout (for monitor_models)")
    args = parser.parse_args()

    if args.json:
        print(get_usage_json(args.db))
    else:
        export_metrics(prom_path=args.prom_path, db_path=args.db)


if __name__ == "__main__":
    main()
