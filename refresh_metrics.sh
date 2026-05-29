#!/bin/bash
# Auto-balance model fallback order (last 7 days of usage)
python3 /root/.hermes/scripts/auto_balance.py --days 7

# Export Pi-hole DNS metrics to Prometheus
python3 /root/.hermes/scripts/pihole_exporter.py
