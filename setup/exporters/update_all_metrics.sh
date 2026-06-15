#!/bin/bash
# ──────────────────────────────────────────────────────────────────────────────
# Hermes 9Router — Full metrics run (including optional exporters)
# Runs smart balancing + Pi-hole DNS metrics (optional add-on).
#
# Pi-hole is an optional extra feature, not part of core routing.
# ──────────────────────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Core: smart balancing with all subsystems
python3 "$SCRIPT_DIR/auto_balance.py" \
    --days 7 \
    --budget 50 \
    --prom-path /var/lib/alloy/9router_metrics.prom

# Optional: Pi-hole DNS metrics (extra feature, not core)
if [ -f /etc/pihole/pihole-FTL.db ]; then
    python3 "$SCRIPT_DIR/pihole_exporter.py"
else
    echo "Pi-hole DB not found, skipping pihole_exporter.py"
fi
