import sqlite3
import yaml
import os
import logging
from datetime import datetime, timedelta
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("hermes_metrics")

DEFAULT_CONFIG_PATH = os.path.expanduser("~/.hermes/config.yaml")
DEFAULT_DB_PATH = os.path.expanduser("~/.hermes/state.db")

def load_config(config_path: str = DEFAULT_CONFIG_PATH) -> dict:
    if not os.path.exists(config_path):
        logger.error(f"Config not found: {config_path}")
        raise FileNotFoundError(f"Config not found: {config_path}")
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)
        if not isinstance(config, dict):
            raise ValueError(f"Config is not a dictionary: {config_path}")
        # Basic schema validation
        required_keys = {"model"}
        if not required_keys.issubset(config.keys()):
            logger.warning(f"Config missing expected keys: {required_keys - config.keys()}")
        return config


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
        logger.warning(f"DB not found: {db_path}")
        return metrics
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        if days:
            cutoff = (datetime.now() - timedelta(days=days)).isoformat()
            cursor.execute(
                "SELECT model, SUM(input_tokens + output_tokens + reasoning_tokens) "
                "FROM sessions WHERE started_at >= ? GROUP BY model",
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
    except sqlite3.Error as e:
        logger.error(f"Database error: {e}")
    finally:
        conn.close()
    return metrics


def sanitize_prometheus_label(name: str) -> str:
    return name.replace("/", "_").replace("-", "_").replace(".", "_")

def get_session_metrics(db_path: str = DEFAULT_DB_PATH) -> Optional[dict]:
    if not os.path.exists(db_path):
        return None
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT model, input_tokens, output_tokens, reasoning_tokens FROM sessions ORDER BY started_at DESC LIMIT 1")
        row = cursor.fetchone()
        if row:
            return {"model": row[0], "used": (row[1] or 0) + (row[2] or 0) + (row[3] or 0)}
    except sqlite3.Error as e:
        logger.error(f"Database error: {e}")
    finally:
        conn.close()
    return None
