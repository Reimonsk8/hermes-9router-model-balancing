#!/bin/bash
python3 /root/.hermes/scripts/auto_balance.py --days 7
python3 /root/.hermes/scripts/pihole_exporter.py
python3 /root/.hermes/scripts/context_exporter.py
