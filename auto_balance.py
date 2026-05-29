#!/usr/bin/env python3
import argparse
import os
import yaml
from hermes_metrics import load_config, get_model_chain, get_usage_metrics, load_model_limits, sanitize_prometheus_label


DEFAULT_PROM_PATH = "/var/lib/alloy/model_usage.prom"


def update_fallback_order(days: int = 7, default_limit: int = 0, dry_run: bool = False, prom_path: str = DEFAULT_PROM_PATH):
    config = load_config()
    chain = get_model_chain(config)
    metrics = get_usage_metrics(days=days)
    limits = load_model_limits(config)

    fallback_entries = [e for e in chain if e["role"] == "fallback"]
    if not fallback_entries:
        print("No fallback providers found in config to reorder.")
        return

    sorted_fallbacks = sorted(fallback_entries, key=lambda e: metrics.get(e["model"], 0))
    default_entry = [e for e in chain if e["role"] == "default"]

    config["fallback_providers"] = [{"provider": e["provider"], "model": e["model"]} for e in sorted_fallbacks]

    config_path = os.path.expanduser("~/.hermes/config.yaml")
    if dry_run:
        print(f"[DRY RUN] Would update {config_path}")
        print(f"[DRY RUN] New fallback order:")
        for i, e in enumerate(sorted_fallbacks, 1):
            tokens = metrics.get(e["model"], 0)
            print(f"  {i}. {e['provider']}/{e['model']} ({tokens:,d} tokens)")
    else:
        with open(config_path, "w") as f:
            yaml.safe_dump(config, f)
        print(f"Updated fallback_providers in {config_path}")
        for i, e in enumerate(sorted_fallbacks, 1):
            tokens = metrics.get(e["model"], 0)
            print(f"  {i}. {e['provider']}/{e['model']} ({tokens:,d} tokens)")

    os.makedirs(os.path.dirname(prom_path), exist_ok=True)
    with open(prom_path, "w") as f:
        f.write("# HELP hermes_model_tokens_used Total tokens used by model\n")
        f.write("# TYPE hermes_model_tokens_used gauge\n")
        f.write("# HELP hermes_model_tokens_limit Token limit per model\n")
        f.write("# TYPE hermes_model_tokens_limit gauge\n")
        f.write("# HELP hermes_model_usage_percent Usage percentage (used/limit * 100)\n")
        f.write("# TYPE hermes_model_usage_percent gauge\n")

        for e in default_entry + sorted_fallbacks:
            model = e["model"]
            label = sanitize_prometheus_label(model)
            used = metrics.get(model, 0)
            limit = limits.get(model, default_limit)
            pct = (used / limit) * 100 if limit > 0 else 0

            f.write(f'hermes_model_tokens_used{{model="{model}"}} {used}\n')
            f.write(f'hermes_model_tokens_limit{{model="{model}"}} {limit}\n')
            f.write(f'hermes_model_usage_percent{{model="{model}"}} {pct:.2f}\n')

    print(f"Wrote Prometheus metrics to {prom_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Auto-balance Hermes model fallback order by usage")
    parser.add_argument("--days", type=int, default=7, help="Look back N days for usage stats (default: 7)")
    parser.add_argument("--default-limit", type=int, default=0, help="Default token limit for models without a configured limit")
    parser.add_argument("--prom-path", default=DEFAULT_PROM_PATH, help="Path for Prometheus metrics output")
    parser.add_argument("--dry-run", action="store_true", help="Print what would change without modifying config")
    args = parser.parse_args()

    update_fallback_order(days=args.days, default_limit=args.default_limit, dry_run=args.dry_run, prom_path=args.prom_path)
