# Hermes 9 Router — Model Balancing & Metrics

Auto-balances Hermes model fallback order by token usage and exports Prometheus metrics for Grafana.

## 1. What It Does & How To Use

### Overview

Three Python scripts + one shared module that run on your Hermes host:

| Script | Purpose |
|--------|---------|
| `auto_balance.py` | Reads token usage from Hermes' SQLite DB, sorts fallback providers by usage (least-used first), rewrites `~/.hermes/config.yaml`, and writes Prometheus metrics |
| `monitor_models.py` | CLI viewer — displays a sorted table of models with tokens used, limit, remaining, and percentage |
| `pihole_exporter.py` | Exports Pi-hole DNS query stats to Prometheus (cumulative counters + 15-minute window) |
| `hermes_metrics.py` | Shared module — config loading, DB queries, model limits |

### How It Works

1. You configure models under `fallback_providers` in `~/.hermes/config.yaml`
2. Optionally set per-model token limits under `model_limits`
3. Run `auto_balance.py` (e.g., via cron every hour):
   - Reads the last 7 days of token usage from `~/.hermes/state.db`
   - Reorders `fallback_providers` so the **least-used** model is tried first
   - Writes Prometheus gauge metrics to `/var/lib/alloy/model_usage.prom`
4. Alloy (or Prometheus textfile collector) scrapes the `.prom` files
5. Grafana visualizes usage, limits, and percentages

### Configuration

Add to `~/.hermes/config.yaml`:

```yaml
fallback_providers:
  - provider: openrouter
    model: anthropic/claude-sonnet-4
  - provider: openai
    model: gpt-4o
  - provider: nous
    model: nous-hermes-3

model_limits:
  anthropic/claude-sonnet-4: 1000000
  gpt-4o: 500000
  nous-hermes-3: 2000000
```

### Running

```bash
# View usage in terminal
python3 monitor_models.py --days 7

# With a default limit for unconfigured models
python3 monitor_models.py --days 7 --limit 1000000

# Auto-balance (update config + write metrics)
python3 auto_balance.py --days 7

# Dry-run (see what would change without writing)
python3 auto_balance.py --days 7 --dry-run

# With a default token limit
python3 auto_balance.py --days 7 --default-limit 1000000

# Pi-hole metrics
python3 pihole_exporter.py

# Or run everything via cron
0 * * * * /root/.hermes/scripts/refresh_metrics.sh
```

## 2. Grafana Dashboard (Copy-Paste JSON)

Create a new dashboard in Grafana → **Import** → paste the JSON below.

Requires a Prometheus data source named `Prometheus` (rename in the `datasource` fields if different).

```json
{
  "__inputs": [],
  "__requires": [],
  "title": "Hermes Router & Pi-hole",
  "uid": "hermes-pihole",
  "panels": [
    {
      "datasource": { "type": "prometheus", "uid": "PROMETHEUS_UID" },
      "fieldConfig": {
        "defaults": {
          "custom": { "stacking": { "mode": "normal" }, "barAlignment": 0 },
          "unit": "short",
          "min": 0
        },
        "overrides": []
      },
      "gridPos": { "h": 8, "w": 12, "x": 0, "y": 0 },
      "id": 1,
      "options": {
        "orientation": "auto",
        "showThresholdLabels": false,
        "showThresholdMarkers": true
      },
      "targets": [
        {
          "expr": "hermes_model_tokens_used",
          "legendFormat": "{{model}}",
          "refId": "A"
        }
      ],
      "title": "Tokens Used per Model",
      "type": "bargauge"
    },
    {
      "datasource": { "type": "prometheus", "uid": "PROMETHEUS_UID" },
      "fieldConfig": {
        "defaults": {
          "custom": { "stacking": { "mode": "normal" }, "barAlignment": 0 },
          "unit": "short",
          "min": 0
        },
        "overrides": []
      },
      "gridPos": { "h": 8, "w": 12, "x": 12, "y": 0 },
      "id": 2,
      "options": {
        "orientation": "auto",
        "showThresholdLabels": false,
        "showThresholdMarkers": true
      },
      "targets": [
        {
          "expr": "hermes_model_tokens_limit",
          "legendFormat": "{{model}}",
          "refId": "A"
        }
      ],
      "title": "Token Limits per Model",
      "type": "bargauge"
    },
    {
      "datasource": { "type": "prometheus", "uid": "PROMETHEUS_UID" },
      "fieldConfig": {
        "defaults": {
          "custom": { "stacking": { "mode": "normal" } },
          "unit": "percent",
          "min": 0,
          "max": 100,
          "thresholds": {
            "mode": "absolute",
            "steps": [
              { "color": "green", "value": null },
              { "color": "orange", "value": 50 },
              { "color": "red", "value": 85 }
            ]
          }
        },
        "overrides": []
      },
      "gridPos": { "h": 8, "w": 24, "x": 0, "y": 8 },
      "id": 3,
      "options": {
        "orientation": "horizontal",
        "showThresholdLabels": false,
        "showThresholdMarkers": true
      },
      "targets": [
        {
          "expr": "hermes_model_usage_percent",
          "legendFormat": "{{model}}",
          "refId": "A"
        }
      ],
      "title": "Usage % per Model",
      "type": "bargauge"
    },
    {
      "datasource": { "type": "prometheus", "uid": "PROMETHEUS_UID" },
      "fieldConfig": {
        "defaults": {
          "unit": "cps",
          "min": 0
        },
        "overrides": []
      },
      "gridPos": { "h": 8, "w": 8, "x": 0, "y": 16 },
      "id": 4,
      "options": {
        "legend": { "calcs": ["mean", "max"], "displayMode": "table", "placement": "bottom" }
      },
      "targets": [
        {
          "expr": "rate(pihole_total_queries[5m])",
          "legendFormat": "Total queries/s",
          "refId": "A"
        },
        {
          "expr": "rate(pihole_blocked_queries[5m])",
          "legendFormat": "Blocked queries/s",
          "refId": "B"
        }
      ],
      "title": "DNS Query Rate (5m avg)",
      "type": "timeseries"
    },
    {
      "datasource": { "type": "prometheus", "uid": "PROMETHEUS_UID" },
      "fieldConfig": {
        "defaults": {
          "unit": "short",
          "min": 0
        },
        "overrides": []
      },
      "gridPos": { "h": 8, "w": 8, "x": 8, "y": 16 },
      "id": 5,
      "options": {
        "legend": { "calcs": ["mean", "max"], "displayMode": "table", "placement": "bottom" }
      },
      "targets": [
        {
          "expr": "increase(pihole_total_queries[15m])",
          "legendFormat": "Total queries/15m",
          "refId": "A"
        },
        {
          "expr": "increase(pihole_blocked_queries[15m])",
          "legendFormat": "Blocked queries/15m",
          "refId": "B"
        }
      ],
      "title": "DNS Queries per 15 min",
      "type": "timeseries"
    },
    {
      "datasource": { "type": "prometheus", "uid": "PROMETHEUS_UID" },
      "fieldConfig": {
        "defaults": {
          "unit": "short",
          "min": 0,
          "thresholds": {
            "mode": "absolute",
            "steps": [
              { "color": "green", "value": null },
              { "color": "orange", "value": 50 },
              { "color": "red", "value": 100 }
            ]
          }
        },
        "overrides": []
      },
      "gridPos": { "h": 8, "w": 8, "x": 16, "y": 16 },
      "id": 6,
      "options": {
        "orientation": "auto",
        "showThresholdLabels": false,
        "showThresholdMarkers": true
      },
      "targets": [
        {
          "expr": "pihole_queries_last_15m{type=\"total\"}",
          "legendFormat": "Last 15m",
          "refId": "A"
        },
        {
          "expr": "pihole_queries_last_15m{type=\"blocked\"}",
          "legendFormat": "Blocked (15m)",
          "refId": "B"
        }
      ],
      "title": "Pi-hole Queries (Last 15m Snapshot)",
      "type": "stat"
    }
  ],
  "refresh": "30s",
  "schemaVersion": 36,
  "tags": ["hermes", "pi-hole", "dns"],
  "templating": { "list": [] },
  "time": { "from": "now-6h", "to": "now" },
  "timepicker": {},
  "timezone": "browser"
}
```

> **Note:** Replace `"uid": "PROMETHEUS_UID"` with your actual Prometheus data source UID. Find it in Grafana → Connections → Data sources → your Prometheus source → UID field.

## 3. Features & Development Status

### ✅ Implemented

| Feature | Status |
|---------|--------|
| Token usage reader from Hermes SQLite state DB | Done |
| Time-windowed queries (`--days` flag for recent usage) | Done |
| Per-model configurable token limits (`model_limits` in config) | Done |
| Automatic reordering of `fallback_providers` by usage (least-used first) | Done |
| Dry-run mode to preview changes | Done |
| CLI usage viewer with used/limit/left/% table | Done |
| Prometheus metrics for tokens used, limit, and usage % per model | Done |
| Pi-hole cumulative DNS counter (total + blocked) | Done |
| Pi-hole 15-minute sliding window gauge | Done |
| Shared module eliminates duplicated DB/config code | Done |
| Grafana dashboard JSON (6 panels) | Done |

### 🚧 In Progress / Planned

| Feature | Priority | Notes |
|---------|----------|-------|
| Per-provider (not just per-model) limits | Low | Some users share a limit across all models under one provider |
| Failure-count-based reordering | Medium | Currently sorts by usage only; could also deprioritize models that error frequently |
| Slack/email alerts when a model exceeds N% of limit | Medium | Would require alerting rules in Grafana or a separate notification script |
| Support for Hermes `fallback_model` (single) configs | Low | Currently only supports the `fallback_providers` list format |
| Config validation / `--check` flag | Low | Validate `model_limits` keys match actual models |
| Systemd timer unit instead of cron | Low | Convenience for non-cron setups |

### 🐛 Known Issues

- `yaml.safe_dump` may reorder top-level config keys (Hermes is tolerant of key order, but worth noting)
- `pihole-FTL.db` path is hardcoded; Pi-hole v5 vs v6 may differ
- The `fallback_providers` config list format is not standard Hermes (which uses `fallback_model` singular) — this repo assumes a custom extended config with multiple fallbacks in a chain
