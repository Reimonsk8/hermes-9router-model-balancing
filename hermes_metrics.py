import sqlite3
import yaml
import os
from datetime import datetime, timedelta
from typing import Optional


DEFAULT_CONFIG_PATH = os.path.expanduser("~/.hermes/config.yaml")
DEFAULT_DB_PATH = os.path.expanduser("~/.hermes/state.db")


def load_config(config_path: str = DEFAULT_CONFIG_PATH) -> dict:
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Config not found: {config_path}")
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


def get_model_chain(config: dict) -> list[dict]:
    chain = []
    default_model = config.get("model", {}).get("default")
    if default_model:
        chain.append({
            "role": "default",
            "model": default_model,
            "provider": config.get("model", {}).get("provider"),
        })
    for entry in config.get("fallback_providers", []):
        model_name = entry.get("model")
        if model_name and model_name not in [m["model"] for m in chain]:
            chain.append({"role": "fallback", **entry})
    return chain


def load_model_limits(config: dict) -> dict[str, int]:
    return config.get("model_limits", {})


def get_usage_metrics(db_path: str = DEFAULT_DB_PATH, days: Optional[int] = None) -> dict[str, int]:
    metrics = {}
    if not os.path.exists(db_path):
        return metrics
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    if days:
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        cursor.execute(
            "SELECT model, SUM(input_tokens + output_tokens + reasoning_tokens) "
            "FROM sessions WHERE created_at >= ? GROUP BY model",
            (cutoff,)
        )
    else:
        cursor.execute(
            "SELECT model, SUM(input_tokens + output_tokens + reasoning_tokens) "
            "FROM sessions GROUP BY model"
        )
    for row in cursor.fetchall():
        if row[0]:
            metrics[row[0]] = row[1]
    conn.close()
    return metrics


def sanitize_prometheus_label(name: str) -> str:
    return name.replace("/", "_").replace("-", "_").replace(".", "_")
