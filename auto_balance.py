#!/usr/bin/env python3
"""
auto_balance.py — Hermes 9Router Smart Fallback Optimizer

Reorders Hermes Agent's fallback_providers using a multi-factor scoring
model that accounts for:
  • Token usage balance (least-used first)
  • Provider health score (success rate, latency)
  • Cost efficiency (pricing per model)
  • Budget zone (green/yellow/orange/red)
  • Quota availability (free-tier limits)
  • Model quality score

Usage:
    python3 auto_balance.py                          # full run
    python3 auto_balance.py --days 7                 # 7-day window
    python3 auto_balance.py --dry-run                # preview only
    python3 auto_balance.py --budget 100             # $100 monthly budget
    python3 auto_balance.py --prom-path /tmp/m.prom  # custom output
    python3 auto_balance.py --daemon --interval 300  # run every 5 min
"""

import argparse
import logging
import time
import signal
import sys
from hermes_metrics import (
    NineRouter, DEFAULT_CONFIG_PATH, DEFAULT_DB_PATH,
    DEFAULT_PRICING_PATH, DEFAULT_PROM_PATH, DEFAULT_BUDGET_MONTHLY,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("auto_balance")

RUNNING = True


def signal_handler(sig, frame):
    global RUNNING
    logger.info("Shutdown signal received, exiting...")
    RUNNING = False


def run_once(args):
    nr = NineRouter(
        config_path=args.config,
        hermes_db=args.db,
        pricing_path=args.pricing,
        output_path=args.prom_path,
        monthly_budget=args.budget,
        days=args.days,
        default_limit=args.default_limit,
    )
    nr.run_all(dry_run=args.dry_run)

    scored = nr.score_models()
    if scored and not args.dry_run:
        logger.info("─" * 60)
        logger.info(f"{'Rank':<6} {'Model':<42} {'Score':>6} {'Quality':>8} {'Health':>8} {'Cost':>6}")
        logger.info("─" * 60)
        for i, s in enumerate(scored):
            logger.info(f"{i+1:<6} {s['model']:<42} {s['score']:>6.1f} {s['quality']:>8.0f} {s['health']:>8.1f} {s['cost_score']:>6.0f}")
        logger.info("─" * 60)

    budget = nr.get_budget_zone()
    logger.info(f"Budget: {budget['label'].upper()} zone — ${budget['spend']:.2f} / ${budget['budget']:.2f} "
                f"({budget['percent']:.1f}%)")
    return nr


def run_daemon(args):
    """Run as a persistent daemon, re-evaluating on an interval."""
    global RUNNING
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    interval = args.interval
    logger.info(f"Starting 9Router daemon (interval={interval}s, dry_run={args.dry_run})")
    logger.info(f"  config={args.config}")
    logger.info(f"  db={args.db}")
    logger.info(f"  pricing={args.pricing}")
    logger.info(f"  budget=${args.budget}/month")

    while RUNNING:
        try:
            nr = run_once(args)
            if not args.dry_run:
                alerts = nr.db.get_active_alerts()
                if alerts:
                    for a in alerts:
                        logger.warning(f"  ALERT [{a['severity'].upper()}] {a['message']}")
        except Exception as e:
            logger.error(f"Daemon cycle error: {e}")

        if RUNNING:
            time.sleep(interval)

    logger.info("Daemon stopped.")


def main():
    parser = argparse.ArgumentParser(
        description="Hermes 9Router — Smart Model Fallback Optimizer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH, help="Hermes config path")
    parser.add_argument("--db", default=DEFAULT_DB_PATH, help="Hermes state.db path")
    parser.add_argument("--pricing", default=DEFAULT_PRICING_PATH, help="Pricing database path")
    parser.add_argument("--prom-path", default=DEFAULT_PROM_PATH, help="Prometheus metrics output")
    parser.add_argument("--budget", type=float, default=DEFAULT_BUDGET_MONTHLY, help="Monthly budget in USD")
    parser.add_argument("--days", type=int, default=7, help="Look back N days for usage stats")
    parser.add_argument("--default-limit", type=int, default=0, help="Default token limit for unconfigured models")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    parser.add_argument("--daemon", action="store_true", help="Run as persistent daemon")
    parser.add_argument("--interval", type=int, default=300, help="Daemon polling interval in seconds")

    args = parser.parse_args()

    if args.daemon:
        run_daemon(args)
    else:
        run_once(args)


if __name__ == "__main__":
    main()
