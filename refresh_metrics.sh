#!/bin/bash
# ──────────────────────────────────────────────────────────────────────────────
# Hermes 9Router — Main cron script
# Runs smart fallback optimization, health monitoring, cost tracking,
# quota management, and Prometheus metrics export.
#
# Schedule: 0 * * * * /root/.hermes/scripts/refresh_metrics.sh
# ──────────────────────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Primary: full smart balancing with all subsystems
python3 "$SCRIPT_DIR/auto_balance.py" \
    --days 7 \
    --budget 50 \
    --prom-path /var/lib/alloy/9router_metrics.prom
