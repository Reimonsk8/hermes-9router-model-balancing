#!/usr/bin/env python3
"""
context_exporter.py — Context Window Metrics Exporter
======================================================
Deprecated: Context metrics are now included in the main Prometheus export
from auto_balance.py via hermes_metrics.export_metrics().

This file is kept as a standalone exporter for users who want context
metrics without the full pipeline. Prefer using:
    python3 auto_balance.py --days 7

Usage:
    python3 context_exporter.py
"""

import os
import tempfile
from hermes_metrics import load_config, get_usage_metrics, get_session_metrics, sanitize_prometheus_label

DEFAULT_PROM_PATH = "/var/lib/alloy/textfile/context.prom"


def export_context_metrics(prom_path: str = DEFAULT_PROM_PATH):
    session = get_session_metrics()
    if not session:
        return

    config = load_config()
    limits = config.get("model_limits", {})
    model = session["model"]
    used = session["used"]
    max_tokens = limits.get(model, 128000)
    remaining = max_tokens - used
    utilization = (used / max_tokens) * 100

    label = sanitize_prometheus_label(model)

    lines = [
        f'# HELP hermes_context_used_tokens Context window tokens used',
        f'# TYPE hermes_context_used_tokens gauge',
        f'hermes_context_used_tokens{{model="{label}"}} {used}',
        f'# HELP hermes_context_max_tokens Maximum context window tokens',
        f'# TYPE hermes_context_max_tokens gauge',
        f'hermes_context_max_tokens{{model="{label}"}} {max_tokens}',
        f'# HELP hermes_context_remaining_tokens Remaining context window tokens',
        f'# TYPE hermes_context_remaining_tokens gauge',
        f'hermes_context_remaining_tokens{{model="{label}"}} {remaining}',
        f'# HELP hermes_context_utilization_percent Context window utilization',
        f'# TYPE hermes_context_utilization_percent gauge',
        f'hermes_context_utilization_percent{{model="{label}"}} {utilization:.2f}',
    ]

    os.makedirs(os.path.dirname(prom_path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(prom_path))
    try:
        with os.fdopen(fd, 'w') as f:
            f.write("\n".join(lines) + "\n")
        os.replace(tmp, prom_path)
    except Exception as e:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise e


if __name__ == "__main__":
    export_context_metrics()
