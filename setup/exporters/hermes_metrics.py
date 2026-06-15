#!/usr/bin/env python3
"""
Hermes 9Router — Core Library
===============================
Companion for Hermes Agent that provides smart fallback optimization,
cost tracking, provider health monitoring, budget management, quota tracking,
and Prometheus metrics export.

Usage:
    from hermes_metrics import (
        NineRouter, load_config, get_model_chain, get_usage_metrics,
        sanitize_prometheus_label, get_session_metrics
    )
    nr = NineRouter()
    nr.run_all(output_path="/var/lib/alloy/9router_metrics.prom")
"""

import sqlite3
import yaml
import os
import json
import logging
import tempfile
import math
from datetime import datetime, timedelta
from typing import Optional, Any
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("hermes_metrics")

# ─── Default Paths ───────────────────────────────────────────────────────────
DEFAULT_CONFIG_PATH = os.path.expanduser("~/.hermes/config.yaml")
DEFAULT_DB_PATH = os.path.expanduser("~/.hermes/state.db")
DEFAULT_9ROUTER_DIR = os.path.expanduser("~/.hermes/9router")
DEFAULT_9ROUTER_DB = os.path.join(DEFAULT_9ROUTER_DIR, "9router.db")
DEFAULT_PRICING_PATH = os.path.join(DEFAULT_9ROUTER_DIR, "pricing.yaml")
if not os.path.exists(DEFAULT_PRICING_PATH):
    DEFAULT_PRICING_PATH = os.path.join(os.path.dirname(__file__), "pricing.yaml")
DEFAULT_PROM_PATH = "/var/lib/alloy/9router_metrics.prom"
DEFAULT_BUDGET_MONTHLY = 50.0
DEFAULT_HEALTH_WINDOW = 100  # number of recent requests to evaluate

# ─── Exception ───────────────────────────────────────────────────────────────

class NineRouterError(Exception):
    pass

# ─── Utility Functions (preserved from original) ─────────────────────────────

def load_config(config_path: str = DEFAULT_CONFIG_PATH) -> dict:
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Config not found: {config_path}")
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)
        if not isinstance(config, dict):
            raise ValueError(f"Config is not a dictionary: {config_path}")
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
    seen = {m["model"] for m in chain if m.get("model")}

    fallback_providers = config.get("fallback_providers")
    fallback_models = config.get("fallback_models")

    if isinstance(fallback_providers, list):
        for entry in fallback_providers:
            model_name = entry.get("model")
            if model_name and model_name not in seen:
                chain.append({"role": "fallback", **entry})
                seen.add(model_name)
    elif isinstance(fallback_models, list):
        for model_name in fallback_models:
            if model_name and model_name not in seen:
                chain.append({
                    "role": "fallback",
                    "model": model_name,
                    "provider": model_name.split("/")[0],
                })
                seen.add(model_name)
    return chain


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
                metrics[row[0]] = row[1] or 0
    except sqlite3.Error as e:
        logger.error(f"Database error: {e}")
    finally:
        conn.close()
    return metrics


def sanitize_prometheus_label(name: str) -> str:
    return name.replace("/", "_").replace("-", "_").replace(".", "_").replace(" ", "_")


def get_session_metrics(db_path: str = DEFAULT_DB_PATH) -> Optional[dict]:
    if not os.path.exists(db_path):
        return None
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT model, input_tokens, output_tokens, reasoning_tokens, started_at "
            "FROM sessions ORDER BY started_at DESC LIMIT 1"
        )
        row = cursor.fetchone()
        if row:
            return {
                "model": row[0],
                "used": (row[1] or 0) + (row[2] or 0) + (row[3] or 0),
                "started_at": row[4],
            }
    except sqlite3.Error as e:
        logger.error(f"Database error: {e}")
    finally:
        conn.close()
    return None


# ─── Pricing Database ────────────────────────────────────────────────────────

def load_pricing(pricing_path: str = DEFAULT_PRICING_PATH) -> dict:
    if not os.path.exists(pricing_path):
        logger.warning(f"Pricing DB not found: {pricing_path}, using empty defaults")
        return {"models": {}, "provider_default_health": {}, "provider_quotas": {}}
    with open(pricing_path, "r") as f:
        data = yaml.safe_load(f) or {}
    return data


def get_model_pricing(model_name: str, pricing: dict) -> dict:
    models = pricing.get("models", {})
    return models.get(model_name, {})


def calculate_cost(input_tokens: int, output_tokens: int, model_pricing: dict) -> float:
    if not model_pricing:
        return 0.0
    input_cost = (input_tokens / 1_000_000) * model_pricing.get("input_per_million", 0)
    output_cost = (output_tokens / 1_000_000) * model_pricing.get("output_per_million", 0)
    return round(input_cost + output_cost, 6)


# ─── Companion Database ──────────────────────────────────────────────────────

class CompanionDB:
    """Manages the 9router companion SQLite database for enriched metrics."""

    SCHEMA = {
        "requests": """
            CREATE TABLE IF NOT EXISTS requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                model TEXT NOT NULL,
                provider TEXT,
                input_tokens INTEGER DEFAULT 0,
                output_tokens INTEGER DEFAULT 0,
                reasoning_tokens INTEGER DEFAULT 0,
                total_tokens INTEGER DEFAULT 0,
                latency_ms INTEGER DEFAULT 0,
                success INTEGER DEFAULT 1,
                error_type TEXT,
                cost_usd REAL DEFAULT 0.0,
                fallback_index INTEGER DEFAULT 0
            )
        """,
        "provider_health": """
            CREATE TABLE IF NOT EXISTS provider_health (
                provider TEXT PRIMARY KEY,
                total_requests INTEGER DEFAULT 0,
                failed_requests INTEGER DEFAULT 0,
                total_latency_ms INTEGER DEFAULT 0,
                health_score REAL DEFAULT 100.0,
                last_updated TEXT
            )
        """,
        "daily_spend": """
            CREATE TABLE IF NOT EXISTS daily_spend (
                date TEXT PRIMARY KEY,
                spend REAL DEFAULT 0.0,
                requests INTEGER DEFAULT 0
            )
        """,
        "monthly_spend": """
            CREATE TABLE IF NOT EXISTS monthly_spend (
                month TEXT PRIMARY KEY,
                spend REAL DEFAULT 0.0,
                requests INTEGER DEFAULT 0
            )
        """,
        "quotas": """
            CREATE TABLE IF NOT EXISTS quotas (
                provider TEXT NOT NULL,
                quota_type TEXT NOT NULL,
                limit_value REAL DEFAULT 0,
                used_value REAL DEFAULT 0,
                last_reset TEXT,
                PRIMARY KEY (provider, quota_type)
            )
        """,
        "routing_history": """
            CREATE TABLE IF NOT EXISTS routing_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                request_type TEXT DEFAULT 'unknown',
                primary_model TEXT,
                fallback_chain TEXT,
                attempts INTEGER DEFAULT 1,
                success INTEGER DEFAULT 1,
                latency_ms INTEGER DEFAULT 0,
                cost_usd REAL DEFAULT 0.0
            )
        """,
        "alerts": """
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                severity TEXT,
                message TEXT,
                acknowledged INTEGER DEFAULT 0
            )
        """,
    }

    def __init__(self, db_path: str = DEFAULT_9ROUTER_DB):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        try:
            for name, ddl in self.SCHEMA.items():
                conn.execute(ddl)
            conn.commit()
        finally:
            conn.close()

    def _conn(self):
        return sqlite3.connect(self.db_path)

    # ── Requests ─────────────────────────────────────────────────────────────

    def sync_requests_from_hermes(self, hermes_db: str = DEFAULT_DB_PATH, days: int = 7):
        """Import sessions from Hermes state.db into our requests table."""
        if not os.path.exists(hermes_db):
            logger.warning(f"Hermes DB not found: {hermes_db}, skipping sync")
            return 0

        hermes_conn = sqlite3.connect(hermes_db)
        our_conn = self._conn()
        imported = 0
        try:
            hermes_c = hermes_conn.cursor()
            cutoff = (datetime.now() - timedelta(days=days)).isoformat()
            hermes_c.execute(
                "SELECT model, input_tokens, output_tokens, reasoning_tokens, "
                "       started_at, 0 AS latency_ms, '' AS error_type "
                "FROM sessions WHERE started_at >= ? ORDER BY started_at",
                (cutoff,)
            )
            rows = hermes_c.fetchall()

            our_c = our_conn.cursor()
            our_c.execute("SELECT MAX(timestamp) FROM requests")
            last_row = our_c.fetchone()
            last_ts = last_row[0] if last_row and last_row[0] else ""

            for row in rows:
                model = row[0]
                inp = row[1] or 0
                out = row[2] or 0
                rsn = row[3] or 0
                ts = row[4] or ""
                lat = row[5] or 0
                err = row[6] or ""

                if ts <= last_ts:
                    continue

                total = inp + out + rsn
                success = 0 if err else 1
                provider = model.split("/")[0] if "/" in model else "unknown"

                our_c.execute(
                    "INSERT INTO requests (timestamp, model, provider, input_tokens, "
                    "output_tokens, reasoning_tokens, total_tokens, latency_ms, "
                    "success, error_type) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (ts, model, provider, inp, out, rsn, total, lat, success, err)
                )
                imported += 1

            our_conn.commit()
            if imported:
                logger.info(f"Imported {imported} new requests from Hermes DB")
        except sqlite3.Error as e:
            logger.error(f"Error syncing requests: {e}")
        finally:
            hermes_conn.close()
            our_conn.close()
        return imported

    # ── Spend Tracking ───────────────────────────────────────────────────────

    def update_spend(self, cost_usd: float, request_count: int = 1):
        """Update daily and monthly spend totals."""
        conn = self._conn()
        try:
            c = conn.cursor()
            today = datetime.now().strftime("%Y-%m-%d")
            this_month = datetime.now().strftime("%Y-%m")

            c.execute(
                "INSERT INTO daily_spend (date, spend, requests) VALUES (?, ?, ?) "
                "ON CONFLICT(date) DO UPDATE SET "
                "spend = spend + excluded.spend, requests = requests + excluded.requests",
                (today, cost_usd, request_count)
            )
            c.execute(
                "INSERT INTO monthly_spend (month, spend, requests) VALUES (?, ?, ?) "
                "ON CONFLICT(month) DO UPDATE SET "
                "spend = spend + excluded.spend, requests = requests + excluded.requests",
                (this_month, cost_usd, request_count)
            )
            conn.commit()
        finally:
            conn.close()

    def get_monthly_spend(self, month: Optional[str] = None) -> float:
        if not month:
            month = datetime.now().strftime("%Y-%m")
        conn = self._conn()
        try:
            c = conn.cursor()
            c.execute("SELECT COALESCE(SUM(spend), 0) FROM monthly_spend WHERE month = ?", (month,))
            return c.fetchone()[0]
        finally:
            conn.close()

    def get_daily_spend(self, date: Optional[str] = None) -> float:
        if not date:
            date = datetime.now().strftime("%Y-%m-%d")
        conn = self._conn()
        try:
            c = conn.cursor()
            c.execute("SELECT COALESCE(SUM(spend), 0) FROM daily_spend WHERE date = ?", (date,))
            return c.fetchone()[0]
        finally:
            conn.close()

    # ── Health Tracking ──────────────────────────────────────────────────────

    def compute_health_scores(self, window: int = DEFAULT_HEALTH_WINDOW) -> dict[str, float]:
        """Compute health scores per provider from recent request history."""
        conn = self._conn()
        scores = {}
        try:
            c = conn.cursor()
            c.execute("SELECT DISTINCT provider FROM requests WHERE provider IS NOT NULL")
            providers = [r[0] for r in c.fetchall()]

            for provider in providers:
                c.execute(
                    "SELECT success, latency_ms FROM requests "
                    "WHERE provider = ? ORDER BY id DESC LIMIT ?",
                    (provider, window)
                )
                rows = c.fetchall()
                if not rows:
                    scores[provider] = 100.0
                    continue

                total = len(rows)
                successes = sum(1 for r in rows if r[0])
                success_rate = successes / total if total > 0 else 1.0

                avg_latency = sum(r[1] for r in rows) / total if total > 0 else 0
                latency_penalty = 1.0
                if avg_latency > 10000:
                    latency_penalty = 0.5
                elif avg_latency > 5000:
                    latency_penalty = 0.8

                score = round(success_rate * 100 * latency_penalty, 1)
                scores[provider] = score

                c.execute(
                    "INSERT OR REPLACE INTO provider_health "
                    "(provider, total_requests, failed_requests, total_latency_ms, health_score, last_updated) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (provider, total, total - successes, sum(r[1] for r in rows), score, datetime.now().isoformat())
                )
            conn.commit()
        finally:
            conn.close()
        return scores

    def get_health_scores(self) -> dict[str, float]:
        conn = self._conn()
        try:
            c = conn.cursor()
            c.execute("SELECT provider, health_score FROM provider_health")
            return {r[0]: r[1] for r in c.fetchall()}
        finally:
            conn.close()

    # ── Quota Management ─────────────────────────────────────────────────────

    def init_quotas(self, pricing: dict):
        """Initialize quota limits from pricing.yaml if not set."""
        quotas_config = pricing.get("provider_quotas", {})
        conn = self._conn()
        try:
            c = conn.cursor()
            for provider, limits in quotas_config.items():
                for qtype, limit_val in limits.items():
                    c.execute(
                        "INSERT OR IGNORE INTO quotas (provider, quota_type, limit_value, used_value, last_reset) "
                        "VALUES (?, ?, ?, 0, ?)",
                        (provider, qtype, limit_val, datetime.now().isoformat())
                    )
            conn.commit()
        finally:
            conn.close()

    def use_quota(self, provider: str, quota_type: str, amount: float = 1.0):
        conn = self._conn()
        try:
            c = conn.cursor()
            c.execute(
                "UPDATE quotas SET used_value = used_value + ? "
                "WHERE provider = ? AND quota_type = ?",
                (amount, provider, quota_type)
            )
            conn.commit()
        finally:
            conn.close()

    def get_quota_status(self, provider: str = None) -> list[dict]:
        conn = self._conn()
        try:
            c = conn.cursor()
            if provider:
                c.execute(
                    "SELECT provider, quota_type, limit_value, used_value, last_reset "
                    "FROM quotas WHERE provider = ?", (provider,)
                )
            else:
                c.execute(
                    "SELECT provider, quota_type, limit_value, used_value, last_reset FROM quotas"
                )
            rows = c.fetchall()
            result = []
            for r in rows:
                remaining = max(r[2] - r[3], 0) if r[2] > 0 else 0
                pct = round((r[3] / r[2]) * 100, 1) if r[2] > 0 else 0
                result.append({
                    "provider": r[0],
                    "type": r[1],
                    "limit": r[2],
                    "used": r[3],
                    "remaining": remaining,
                    "percent": pct,
                })
            return result
        finally:
            conn.close()

    def reset_daily_quotas(self):
        """Reset daily quota counters (call once per day)."""
        conn = self._conn()
        try:
            c = conn.cursor()
            c.execute(
                "UPDATE quotas SET used_value = 0, last_reset = ? "
                "WHERE quota_type = 'daily'",
                (datetime.now().isoformat(),)
            )
            conn.commit()
        finally:
            conn.close()

    # ── Routing History ──────────────────────────────────────────────────────

    def log_routing_decision(self, request_type: str, primary_model: str,
                             fallback_chain: list, attempts: int, success: bool,
                             latency_ms: int, cost_usd: float):
        conn = self._conn()
        try:
            c = conn.cursor()
            c.execute(
                "INSERT INTO routing_history "
                "(timestamp, request_type, primary_model, fallback_chain, attempts, success, latency_ms, cost_usd) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (datetime.now().isoformat(), request_type, primary_model,
                 json.dumps(fallback_chain), attempts, int(success), latency_ms, cost_usd)
            )
            conn.commit()
        finally:
            conn.close()

    # ── Alerts ───────────────────────────────────────────────────────────────

    def add_alert(self, severity: str, message: str):
        conn = self._conn()
        try:
            c = conn.cursor()
            c.execute(
                "INSERT INTO alerts (timestamp, severity, message) VALUES (?, ?, ?)",
                (datetime.now().isoformat(), severity, message)
            )
            conn.commit()
            logger.warning(f"[{severity.upper()}] {message}")
        finally:
            conn.close()

    def get_active_alerts(self, severity: Optional[str] = None) -> list[dict]:
        conn = self._conn()
        try:
            c = conn.cursor()
            if severity:
                c.execute(
                    "SELECT id, timestamp, severity, message FROM alerts "
                    "WHERE acknowledged = 0 AND severity = ? ORDER BY id DESC LIMIT 10",
                    (severity,)
                )
            else:
                c.execute(
                    "SELECT id, timestamp, severity, message FROM alerts "
                    "WHERE acknowledged = 0 ORDER BY id DESC LIMIT 20"
                )
            return [
                {"id": r[0], "timestamp": r[1], "severity": r[2], "message": r[3]}
                for r in c.fetchall()
            ]
        finally:
            conn.close()


# ─── NineRouter — Main Engine ────────────────────────────────────────────────

class NineRouter:
    """Main engine coordinating all subsystems for smart fallback ordering."""

    def __init__(
        self,
        config_path: str = DEFAULT_CONFIG_PATH,
        hermes_db: str = DEFAULT_DB_PATH,
        pricing_path: str = DEFAULT_PRICING_PATH,
        output_path: str = DEFAULT_PROM_PATH,
        monthly_budget: float = DEFAULT_BUDGET_MONTHLY,
        days: int = 7,
        default_limit: int = 0,
    ):
        self.config_path = config_path
        self.hermes_db = hermes_db
        self.pricing_path = pricing_path
        self.output_path = output_path
        self.monthly_budget = monthly_budget
        self.days = days
        self.default_limit = default_limit

        self.db = CompanionDB()
        self.pricing = load_pricing(pricing_path)
        self.config = None
        self.chain = []
        self.metrics = {}
        self.limits = {}
        self._fallback_key = "fallback_providers"

    def load(self):
        """Load config, model chain, usage metrics, and limits."""
        self.config = load_config(self.config_path)
        self.chain = get_model_chain(self.config)

        if isinstance(self.config.get("fallback_models"), list):
            self._fallback_key = "fallback_models"
        elif isinstance(self.config.get("fallback_providers"), list):
            self._fallback_key = "fallback_providers"

        self.metrics = get_usage_metrics(self.hermes_db, days=self.days)
        self.limits = self.config.get("model_limits", {})
        return self

    def sync(self):
        """Sync Hermes sessions into companion DB and compute derived data."""
        self.db.sync_requests_from_hermes(self.hermes_db, days=self.days)
        self.db.compute_health_scores()
        self.db.init_quotas(self.pricing)
        self._compute_spend_from_requests()
        self._evaluate_alerts()
        return self

    def _compute_spend_from_requests(self):
        """Recompute spend from requests with pricing data."""
        conn = self.db._conn()
        try:
            c = conn.cursor()
            c.execute(
                "SELECT model, input_tokens, output_tokens, cost_usd FROM requests WHERE cost_usd = 0"
            )
            rows = c.fetchall()
            for row in rows:
                model = row[0]
                inp = row[1]
                out = row[2]
                model_pricing = get_model_pricing(model, self.pricing)
                if model_pricing:
                    cost = calculate_cost(inp, out, model_pricing)
                    c.execute("UPDATE requests SET cost_usd = ? WHERE model = ? AND input_tokens = ? AND output_tokens = ? AND cost_usd = 0",
                              (cost, model, inp, out))
            conn.commit()
        finally:
            conn.close()

    def _evaluate_alerts(self):
        """Evaluate conditions and add alerts."""
        scores = self.db.get_health_scores()
        for provider, score in scores.items():
            if score < 50:
                self.db.add_alert("critical", f"Provider {provider} health score is {score}")
            elif score < 70:
                self.db.add_alert("warning", f"Provider {provider} health score dropped to {score}")

        budget_spend = self.db.get_monthly_spend()
        budget_pct = (budget_spend / self.monthly_budget) * 100 if self.monthly_budget > 0 else 0
        if budget_pct > 90:
            self.db.add_alert("critical", f"Budget at {budget_pct:.0f}% (${budget_spend:.2f}/${self.monthly_budget:.2f})")
        elif budget_pct > 75:
            self.db.add_alert("warning", f"Budget at {budget_pct:.0f}% (${budget_spend:.2f}/${self.monthly_budget:.2f})")

        for quota in self.db.get_quota_status():
            if quota["percent"] > 85:
                self.db.add_alert("warning",
                    f"Quota {quota['provider']}/{quota['type']} at {quota['percent']:.0f}%")

    # ── Budget Zone ──────────────────────────────────────────────────────────

    def get_budget_zone(self) -> dict:
        """Determine budget zone (0=green, 1=yellow, 2=orange, 3=red)."""
        spend = self.db.get_monthly_spend()
        pct = (spend / self.monthly_budget) * 100 if self.monthly_budget > 0 else 0

        if pct < 50:
            zone = 0
            label = "green"
        elif pct < 75:
            zone = 1
            label = "yellow"
        elif pct < 90:
            zone = 2
            label = "orange"
        else:
            zone = 3
            label = "red"

        daily = self.db.get_daily_spend()
        projected = (daily * 30) if daily > 0 else 0

        return {
            "zone": zone,
            "label": label,
            "spend": round(spend, 2),
            "budget": self.monthly_budget,
            "percent": round(pct, 1),
            "remaining": round(max(self.monthly_budget - spend, 0), 2),
            "daily_spend": round(daily, 4),
            "projected": round(projected, 2),
        }

    # ── Complexity Analysis ──────────────────────────────────────────────────

    def classify_request(self, prompt_length: int = 0, task_hint: str = "") -> str:
        """Classify request complexity based on available hints.
        Returns: 'simple', 'medium', 'complex'
        """
        hint_lower = task_hint.lower()
        complex_keywords = ["research", "architecture", "plan", "design", "analyze",
                            "refactor", "complex", "large", "full", "complete"]
        simple_keywords = ["translate", "summarize", "explain", "define", "what",
                           "short", "fix", "typo", "grammar"]

        if any(k in hint_lower for k in complex_keywords) or prompt_length > 4000:
            return "complex"
        if any(k in hint_lower for k in simple_keywords) or prompt_length < 200:
            return "simple"
        return "medium"

    def get_tier_for_complexity(self, complexity: str) -> str:
        tiers = {
            "simple": "free",
            "medium": "budget",
            "complex": "premium",
        }
        return tiers.get(complexity, "budget")

    # ── Smart Scoring ────────────────────────────────────────────────────────

    def score_models(self) -> list[dict]:
        """Score all models in the chain and return sorted list."""
        fallback_entries = [e for e in self.chain if e["role"] == "fallback"]
        budget_zone = self.get_budget_zone()
        health_scores = self.db.get_health_scores()
        quota_status = self.db.get_quota_status()

        scored = []
        for entry in fallback_entries:
            model = entry["model"]
            provider = entry.get("provider", "unknown")
            model_pricing = get_model_pricing(model, self.pricing)
            used = self.metrics.get(model, 0)
            limit = self.limits.get(model, self.default_limit)

            # Quality score (0-100)
            quality = model_pricing.get("quality_score", 70)

            # Availability / health score (0-100)
            health = health_scores.get(provider, 95)
            usage_pct = (used / limit) * 100 if limit > 0 else 0
            if usage_pct > 90:
                health *= 0.3
            elif usage_pct > 75:
                health *= 0.6

            # Quota score (0-100)
            quota_score = 100
            for q in quota_status:
                if q["provider"] == provider:
                    if q["percent"] > 90:
                        quota_score = 10
                    elif q["percent"] > 75:
                        quota_score = 40
                    elif q["percent"] > 50:
                        quota_score = 70

            # Latency score (0-100) — shorter is better
            conn = self.db._conn()
            latency_score = 100
            try:
                c = conn.cursor()
                c.execute(
                    "SELECT AVG(latency_ms) FROM requests WHERE provider = ? AND latency_ms > 0",
                    (provider,)
                )
                avg_lat = c.fetchone()[0]
                if avg_lat:
                    if avg_lat > 10000:
                        latency_score = 30
                    elif avg_lat > 5000:
                        latency_score = 60
                    elif avg_lat > 2000:
                        latency_score = 80
            finally:
                conn.close()

            # Cost score (0-100) — cheaper is better
            inp_price = model_pricing.get("input_per_million", 0)
            out_price = model_pricing.get("output_per_million", 0)
            total_price = inp_price + out_price
            if total_price <= 0:
                cost_score = 100
            elif total_price <= 0.5:
                cost_score = 90
            elif total_price <= 2:
                cost_score = 70
            elif total_price <= 10:
                cost_score = 40
            else:
                cost_score = 10

            # Budget zone multiplier
            zone = budget_zone["zone"]
            tier = model_pricing.get("tier", "budget")
            if zone == 3:  # red — local/free only
                budget_mult = 1.0 if tier == "free" else 0.1
            elif zone == 2:  # orange — prefer free/budget
                budget_mult = 1.0 if tier in ("free", "budget") else 0.3
            elif zone == 1:  # yellow — prefer budget
                budget_mult = 0.7 if tier == "premium" else 1.0
            else:  # green — anything goes
                budget_mult = 1.0

            # Usage balance — prefer less-used models
            if limit > 0:
                balance = 100 - usage_pct
            else:
                balance = 50

            # Final score (weighted geometric mean)
            raw_score = (
                (quality ** 0.25) *
                ((health * budget_mult) ** 0.25) *
                (quota_score ** 0.15) *
                (latency_score ** 0.10) *
                (cost_score ** 0.15) *
                (balance ** 0.10)
            )

            scored.append({
                "model": model,
                "provider": provider,
                "role": entry["role"],
                "score": round(raw_score, 1),
                "quality": quality,
                "health": round(health, 1),
                "quota": quota_score,
                "latency": latency_score,
                "cost_score": cost_score,
                "budget_mult": budget_mult,
                "balance": round(balance, 1),
                "used": used,
                "limit": limit,
            })

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored

    # ── Fallback Ordering ────────────────────────────────────────────────────

    def get_ordered_fallback(self) -> list[dict]:
        """Get fallback providers sorted by smart score."""
        scored = self.score_models()
        return [
            {"provider": s["provider"], "model": s["model"], "score": s["score"]}
            for s in scored
        ]

    def update_config(self, dry_run: bool = False) -> bool:
        """Rewrite config.yaml with smart-ordered fallback providers."""
        ordered = self.get_ordered_fallback()
        if not ordered:
            logger.warning("No fallback entries to order")
            return False

        if dry_run:
            logger.info(f"[DRY RUN] New fallback order:")
            for i, entry in enumerate(ordered):
                logger.info(f"  {i+1}. {entry['provider']}/{entry['model']} (score: {entry['score']})")
            return True

        if self._fallback_key == "fallback_models":
            self.config["fallback_models"] = [e["model"] for e in ordered]
        else:
            self.config["fallback_providers"] = [
                {"provider": e["provider"], "model": e["model"]}
                for e in ordered
            ]

        with open(self.config_path, "w") as f:
            yaml.safe_dump(self.config, f)

        logger.info(f"Updated {self._fallback_key} in {self.config_path}")
        logger.info(f"  Best: {ordered[0]['provider']}/{ordered[0]['model']} ({ordered[0]['score']})")
        logger.info(f"  Worst: {ordered[-1]['provider']}/{ordered[-1]['model']} ({ordered[-1]['score']})")
        return True

    # ── Prometheus Export ────────────────────────────────────────────────────

    def export_metrics(self, output_path: Optional[str] = None):
        """Export all metrics to Prometheus text file."""
        path = output_path or self.output_path
        scored = self.score_models()
        budget_zone = self.get_budget_zone()
        health_scores = self.db.get_health_scores()
        quota_status = self.db.get_quota_status()

        lines = []

        # ── Helpers ──
        def w(line):
            lines.append(line)

        def sanitize(val):
            if isinstance(val, str):
                return val.replace("\\", "\\\\").replace('"', '\\"')
            return val

        # ── Existing Token Metrics ──
        w("# HELP hermes_model_tokens_used Total tokens used by model (7d window)")
        w("# TYPE hermes_model_tokens_used gauge")
        for entry in self.chain:
            model = entry["model"]
            used = self.metrics.get(model, 0)
            w(f'hermes_model_tokens_used{{model="{sanitize(model)}"}} {used}')

        w("# HELP hermes_model_tokens_limit Token limit per model")
        w("# TYPE hermes_model_tokens_limit gauge")
        for entry in self.chain:
            model = entry["model"]
            limit = self.limits.get(model, self.default_limit)
            w(f'hermes_model_tokens_limit{{model="{sanitize(model)}"}} {limit}')

        w("# HELP hermes_model_usage_percent Usage percentage (used/limit * 100)")
        w("# TYPE hermes_model_usage_percent gauge")
        for entry in self.chain:
            model = entry["model"]
            used = self.metrics.get(model, 0)
            limit = self.limits.get(model, self.default_limit)
            pct = (used / limit) * 100 if limit > 0 else 0
            w(f'hermes_model_usage_percent{{model="{sanitize(model)}"}} {pct:.2f}')

        # ── Context Metrics ──
        session = get_session_metrics(self.hermes_db)
        if session:
            model = session["model"]
            used = session["used"]
            max_tok = self.limits.get(model, 128000)
            remaining = max_tok - used
            utilization = (used / max_tok) * 100

            w("# HELP hermes_context_used_tokens Context window tokens used")
            w("# TYPE hermes_context_used_tokens gauge")
            w(f'hermes_context_used_tokens{{model="{sanitize(model)}"}} {used}')
            w("# HELP hermes_context_max_tokens Maximum context window tokens")
            w("# TYPE hermes_context_max_tokens gauge")
            w(f'hermes_context_max_tokens{{model="{sanitize(model)}"}} {max_tok}')
            w("# HELP hermes_context_remaining_tokens Remaining context window tokens")
            w("# TYPE hermes_context_remaining_tokens gauge")
            w(f'hermes_context_remaining_tokens{{model="{sanitize(model)}"}} {remaining}')
            w("# HELP hermes_context_utilization_percent Context window utilization")
            w("# TYPE hermes_context_utilization_percent gauge")
            w(f'hermes_context_utilization_percent{{model="{sanitize(model)}"}} {utilization:.2f}')

        # ── Cost Metrics ──
        w("# HELP hermes_cost_total Cumulative spend in USD")
        w("# TYPE hermes_cost_total gauge")
        w(f'hermes_cost_total {budget_zone["spend"]}')

        w("# HELP hermes_cost_monthly_budget Monthly budget limit in USD")
        w("# TYPE hermes_cost_monthly_budget gauge")
        w(f'hermes_cost_monthly_budget {self.monthly_budget}')

        w("# HELP hermes_cost_budget_remaining Remaining budget in USD")
        w("# TYPE hermes_cost_budget_remaining gauge")
        w(f'hermes_cost_budget_remaining {budget_zone["remaining"]}')

        w("# HELP hermes_cost_daily_spend Current daily spend in USD")
        w("# TYPE hermes_cost_daily_spend gauge")
        w(f'hermes_cost_daily_spend {budget_zone["daily_spend"]}')

        w("# HELP hermes_cost_projected_monthly Projected monthly spend in USD")
        w("# TYPE hermes_cost_projected_monthly gauge")
        w(f'hermes_cost_projected_monthly {budget_zone["projected"]}')

        w("# HELP hermes_cost_budget_percent Budget usage percentage")
        w("# TYPE hermes_cost_budget_percent gauge")
        w(f'hermes_cost_budget_percent {budget_zone["percent"]}')

        # ── Budget Zone ──
        w("# HELP hermes_budget_zone Current budget zone (0=green,1=yellow,2=orange,3=red)")
        w("# TYPE hermes_budget_zone gauge")
        w(f'hermes_budget_zone {budget_zone["zone"]}')
        w(f'hermes_budget_zone_info{{zone="{budget_zone["label"]}"}} 1')

        # ── Health Scores ──
        if health_scores:
            w("# HELP hermes_health_score Provider health score (0-100)")
            w("# TYPE hermes_health_score gauge")
            for provider, score in health_scores.items():
                w(f'hermes_health_score{{provider="{sanitize(provider)}"}} {score}')

        # ── Quota Status ──
        if quota_status:
            w("# HELP hermes_quota_limit Quota limit per provider/type")
            w("# TYPE hermes_quota_limit gauge")
            w("# HELP hermes_quota_used Quota used per provider/type")
            w("# TYPE hermes_quota_used gauge")
            w("# HELP hermes_quota_remaining Quota remaining per provider/type")
            w("# TYPE hermes_quota_remaining gauge")
            w("# HELP hermes_quota_percent Quota usage percentage")
            w("# TYPE hermes_quota_percent gauge")
            for q in quota_status:
                lbl = f'provider="{sanitize(q["provider"])}",type="{q["type"]}"'
                w(f'hermes_quota_limit{{{lbl}}} {q["limit"]}')
                w(f'hermes_quota_used{{{lbl}}} {q["used"]}')
                w(f'hermes_quota_remaining{{{lbl}}} {q["remaining"]}')
                w(f'hermes_quota_percent{{{lbl}}} {q["percent"]}')

        # ── Model Scores ──
        if scored:
            w("# HELP hermes_model_score Smart model score (0-100)")
            w("# TYPE hermes_model_score gauge")
            w("# HELP hermes_model_rank Position in fallback order (1=best)")
            w("# TYPE hermes_model_rank gauge")
            for i, s in enumerate(scored):
                lbl = f'model="{sanitize(s["model"])}",provider="{sanitize(s["provider"])}"'
                w(f'hermes_model_score{{{lbl}}} {s["score"]}')
                w(f'hermes_model_rank{{{lbl}}} {i + 1}')

        # ── Active Alerts ──
        alerts = self.db.get_active_alerts()
        w("# HELP hermes_active_alerts Active alerts count by severity")
        w("# TYPE hermes_active_alerts gauge")
        warning_count = sum(1 for a in alerts if a["severity"] == "warning")
        critical_count = sum(1 for a in alerts if a["severity"] == "critical")
        w(f'hermes_active_alerts{{severity="warning"}} {warning_count}')
        w(f'hermes_active_alerts{{severity="critical"}} {critical_count}')

        # ── Write atomically ──
        out_dir = os.path.dirname(path)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=out_dir or os.getcwd())
        try:
            with os.fdopen(fd, "w") as f:
                f.write("\n".join(lines) + "\n")
            os.replace(tmp, path)
            logger.info(f"Exported {len(scored)} model scores, {len(health_scores)} health scores, "
                        f"{len(quota_status)} quotas to {path}")
        except Exception as e:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise e

    # ── Run All ──────────────────────────────────────────────────────────────

    def run_all(self, dry_run: bool = False):
        """Run the full pipeline: load, sync, score, reorder, export."""
        self.load()
        self.sync()
        self.update_config(dry_run=dry_run)
        self.export_metrics()
        return self
