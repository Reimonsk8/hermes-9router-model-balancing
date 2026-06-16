#!/usr/bin/env python3
"""
hermes_exporter.py - Real metrics from 9router DB only. No fake/placeholder data.
"""
import sqlite3
import os
import tempfile
from datetime import datetime, timezone

DB_PATH = "/root/.9router/db/data.sqlite"
OUTPUT_PATH = "/var/lib/alloy/textfile/hermes.prom"
BUDGET_MONTHLY = 50.0

def export():
    conn = sqlite3.connect(DB_PATH)

    total = conn.execute("""
        SELECT COUNT(*), COALESCE(SUM(promptTokens), 0), COALESCE(SUM(completionTokens), 0),
               COALESCE(SUM(cost), 0)
        FROM usageHistory
    """).fetchone()
    total_reqs = total[0] or 0
    total_cost = total[3] or 0.0

    models = conn.execute("""
        SELECT model, COUNT(*), COALESCE(SUM(promptTokens), 0),
               COALESCE(SUM(completionTokens), 0), COALESCE(SUM(cost), 0)
        FROM usageHistory GROUP BY model
    """).fetchall()

    month = datetime.now(timezone.utc).strftime("%Y-%m")
    monthly = conn.execute("""
        SELECT COALESCE(SUM(cost), 0) FROM usageHistory
        WHERE substr(timestamp, 1, 7) = ?
    """, (month,)).fetchone()[0]

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    daily = conn.execute("""
        SELECT COALESCE(SUM(cost), 0) FROM usageHistory
        WHERE substr(timestamp, 1, 10) = ?
    """, (today,)).fetchone()[0]

    conn.close()

    lines = []

    # Totals
    lines.append("# HELP hermes_total_requests Total requests")
    lines.append("# TYPE hermes_total_requests gauge")
    lines.append(f"hermes_total_requests {total_reqs}")

    lines.append("# HELP hermes_cost_total Cumulative spend in USD")
    lines.append("# TYPE hermes_cost_total gauge")
    lines.append(f"hermes_cost_total {total_cost:.6f}")

    lines.append("# HELP hermes_cost_daily_spend Today's spend in USD")
    lines.append("# TYPE hermes_cost_daily_spend gauge")
    lines.append(f"hermes_cost_daily_spend {daily:.6f}")

    lines.append("# HELP hermes_cost_monthly_spend This month spend in USD")
    lines.append("# TYPE hermes_cost_monthly_spend gauge")
    lines.append(f"hermes_cost_monthly_spend {monthly:.6f}")

    lines.append("# HELP hermes_cost_monthly_budget Monthly budget in USD")
    lines.append("# TYPE hermes_cost_monthly_budget gauge")
    lines.append(f"hermes_cost_monthly_budget {BUDGET_MONTHLY}")

    remaining = max(0, BUDGET_MONTHLY - monthly)
    lines.append("# HELP hermes_cost_budget_remaining Budget remaining in USD")
    lines.append("# TYPE hermes_cost_budget_remaining gauge")
    lines.append(f"hermes_cost_budget_remaining {remaining:.6f}")

    projected = (monthly / max(1, datetime.now(timezone.utc).day)) * 30
    lines.append("# HELP hermes_cost_projected_monthly Projected month-end spend")
    lines.append("# TYPE hermes_cost_projected_monthly gauge")
    lines.append(f"hermes_cost_projected_monthly {projected:.6f}")

    budget_pct = (monthly / BUDGET_MONTHLY) * 100
    lines.append("# HELP hermes_cost_budget_percent Budget usage percentage")
    lines.append("# TYPE hermes_cost_budget_percent gauge")
    lines.append(f"hermes_cost_budget_percent {budget_pct:.1f}")

    zone = 0 if budget_pct < 50 else (1 if budget_pct < 75 else (2 if budget_pct < 90 else 3))
    lines.append("# HELP hermes_budget_zone Budget zone (0=G, 1=Y, 2=O, 3=R)")
    lines.append("# TYPE hermes_budget_zone gauge")
    lines.append(f"hermes_budget_zone {zone}")

    lines.append("")

    # Per-model real metrics
    for m in models:
        model_name, reqs, inp, out, cost = m
        label = model_name.replace("/", "_").replace("-", "_").replace(" ", "_")
        label = "".join(c for c in label if c.isalnum() or c == "_")

        lines.append(f'hermes_model_requests_total{{model="{label}"}} {reqs}')
        lines.append(f'hermes_model_input_tokens{{model="{label}"}} {inp}')
        lines.append(f'hermes_model_output_tokens{{model="{label}"}} {out}')
        lines.append(f'hermes_model_cost_dollars{{model="{label}"}} {cost:.6f}')

    content = "\n".join(lines) + "\n"

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(OUTPUT_PATH))
    with os.fdopen(fd, "w") as f:
        f.write(content)
    os.replace(tmp, OUTPUT_PATH)

if __name__ == "__main__":
    export()
