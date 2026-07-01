# Hermes 9Router — Smart Model Fallback Optimizer

Companion for [Hermes Agent](https://github.com/NousResearch/hermes-agent) that automatically optimizes `fallback_providers` ordering using **cost-aware, health-aware, quota-aware, budget-aware** multi-factor scoring. Exports rich Prometheus metrics for Grafana observability.

## Quick Start

```bash
# Full optimization run (reads Hermes DB + config, scores, reorders, exports)
python3 auto_balance.py --days 7 --budget 50

# Preview without making changes
python3 auto_balance.py --dry-run

# CLI usage viewer with smart scores
python3 monitor_models.py --days 7 --scores

# CLI viewer with budget and alerts
python3 monitor_models.py --days 7 --budget --alerts

# Daemon mode (persistent, polls every 5 minutes)
python3 auto_balance.py --daemon --interval 300

# Cron (every hour)
0 * * * * /root/.hermes/scripts/refresh_metrics.sh
```

## What It Does

1. **Reads** Hermes Agent's `~/.hermes/config.yaml` and `~/.hermes/state.db`
2. **Syncs** session data into a companion database (`~/.hermes/9router/9router.db`)
3. **Scores** every model in the fallback chain using 6 weighted factors:
   - Quality score (from pricing DB)
   - Provider health (success rate × latency)
   - Quota remaining (RPM/daily limits)
   - Latency performance
   - Cost efficiency
   - Usage balance
4. **Reorders** `fallback_providers` so the best model is tried first
5. **Exports** 30+ Prometheus metrics for Grafana dashboards
6. **Alerts** when providers degrade, budgets run low, or quotas exhaust

## Scoring Formula

```
score = quality^0.25 × (health × budget_mult)^0.25 × quota^0.15 × latency^0.10 × cost^0.15 × balance^0.10
```

Budget zones dynamically adjust strategy:
| Zone | Spend | Behavior |
|------|-------|----------|
| 🟢 Green | < 50% | Best model first |
| 🟡 Yellow | 50-75% | Prefer efficient |
| 🟠 Orange | 75-90% | Aggressive savings |
| 🔴 Red | > 90% | Free models only |

## Files

| File | Purpose |
|------|---------|
| `hermes_metrics.py` | Core library — DB, pricing, health, budget, scoring, alerts |
| `auto_balance.py` | CLI entry point — single run or persistent daemon |
| `monitor_models.py` | CLI viewer — usage, scores, budget, alerts, JSON output |
| `pihole_exporter.py` | **[Optional extra]** Pi-hole DNS metrics exporter |
| `pricing.yaml` | Pricing database — 15+ models with costs, quality, quotas |
| `refresh_metrics.sh` | Cron script (core only) |
| `update_all_metrics.sh` | Full run including optional Pi-hole |
| `dashboard-example.json` | Grafana dashboard with all panels |

## Grafana Dashboard

Import `dashboard-example.json` into Grafana. Requires a Prometheus data source named `grafanacloud-prom` (rename if needed).

Dashboard sections:
- **Spending** — total, daily, projected, budget zone
- **Provider Health** — health scores, success rate, latency
- **Model Usage** — tokens used, limits, usage %, smart scores
- **Quotas** — remaining RPM/daily per provider
- **Alerts** — active warnings and criticals
- **Pi-hole (optional)** — DNS stats (collapsible row)

## Prometheus Metrics

| Metric | Description |
|--------|-------------|
| `hermes_model_tokens_used` | Tokens used per model (7d) |
| `hermes_model_tokens_limit` | Token limit per model |
| `hermes_model_usage_percent` | Usage % per model |
| `hermes_model_score` | Smart score per model |
| `hermes_model_rank` | Rank in fallback order |
| `hermes_health_score` | Health score per provider |
| `hermes_cost_total` | Cumulative spend (USD) |
| `hermes_cost_budget_percent` | Budget used % |
| `hermes_budget_zone` | Current zone (0-3) |
| `hermes_quota_percent` | Quota used % per provider |
| `hermes_active_alerts` | Active alert count |
| `hermes_context_*` | Context window metrics |

## Configuration

### `pricing.yaml` (customize per deployment)

```yaml
models:
  claude-sonnet-4:
    input_per_million: 3.00
    output_per_million: 15.00
    provider: anthropic
    quality_score: 95
    tier: premium

provider_default_health:
  groq: 98
  openrouter: 95

provider_quotas:
  groq:
    rpm: 30
    daily: 1000
```

### CLI Options

```bash
python3 auto_balance.py --help
  --config PATH       Hermes config path
  --db PATH           Hermes state.db path
  --pricing PATH      Pricing database path
  --prom-path PATH    Prometheus output path
  --budget FLOAT      Monthly budget (USD)
  --days INT          Usage window days
  --default-limit INT Default token limit
  --dry-run           Preview only
  --daemon            Persistent daemon mode
  --interval INT      Daemon poll interval (s)
```

## Daemon Mode

```bash
# Run as a service that continuously monitors and optimizes
python3 auto_balance.py --daemon --interval 300 \
    --budget 50 --days 7

# Systemd unit example:
# [Unit]
# Description=Hermes 9Router Daemon
# [Service]
# ExecStart=/usr/bin/python3 /root/.hermes/scripts/auto_balance.py --daemon
# Restart=always
# [Install]
# WantedBy=multi-user.target
```

## Pi-hole (Optional Extra)

Pi-hole DNS metrics are exported via `pihole_exporter.py` as a separate, optional feature. It is not required for model balancing.

```bash
# Export Pi-hole metrics to Prometheus
python3 pihole_exporter.py
```

## Development

All phases of the [development plan](development-plan.md) are implemented:

1. ✅ Enhanced Metrics Collection
2. ✅ Cost Engine
3. ✅ Provider Health Monitor
4. ✅ Complexity Analyzer
5. ✅ Budget-Aware Optimization
6. ✅ Smart Fallback Ordering
7. ✅ Quota Management
8. ✅ Alerts & Notifications
9. ✅ Grafana Dashboard
10. ✅ Learning Router (routing history)
11. ✅ Code Hardening

## Monitoring Setup (Grafana Alloy + Textfile Collector)

This repository includes a complete Grafana Cloud monitoring setup using [Grafana Alloy](https://grafana.com/docs/alloy/latest/).

### Architecture

```
hermes_metrics.py / auto_balance.py
  → /var/lib/alloy/9router_metrics.prom  (hermes_model_* metrics)
pihole_exporter.py
  → /var/lib/alloy/pihole_metrics.prom   (Pi-hole DNS metrics)
       ↓
  textfile collector (node_exporter)
       ↓
  Alloy → Grafana Cloud Prometheus
```

### Quick Start

```bash
# 1. Run the setup script (copies config, links prom files, adds cron jobs)
bash setup/configure.sh

# 2. Verify Alloy is running
rc-service alloy status

# 3. Check logs
tail -f /var/log/alloy/alloy.log
```

### Files

| File | Purpose |
|------|---------|
| `setup/alloy.config.alloy` | Grafana Alloy configuration (textfile collector, remote write) |
| `setup/configure.sh` | One-shot setup script for textfile collector + cron |
| `setup/current_crontab.txt` | Snapshot of current cron jobs |
| `setup/exporters/` | Copies of all metric exporter scripts |

### Cron Jobs

The following cron entries are added by `setup/configure.sh`:

```cron
# Hermes metrics generators (every 15 min)
*/15 * * * * cd /root/.hermes/scripts && python3 pihole_exporter.py >/dev/null 2>&1

# Model balancing (every 30 min)
*/30 * * * * cd /root/.hermes/scripts && python3 auto_balance.py --days 7 --budget 50 >/dev/null 2>&1
```

### Textfile Collector

The node_exporter textfile collector reads `.prom` files from `/var/lib/alloy/textfile/`.
All metric exporters write their `.prom` files here (via symlinks) so Alloy automatically collects them.

```bash
ls -la /var/lib/alloy/textfile/
# 9router_metrics.prom → /var/lib/alloy/9router_metrics.prom
# pihole_metrics.prom → /var/lib/alloy/pihole_metrics.prom
```

### Restarting Alloy

```bash
rc-service alloy restart
tail -f /var/log/alloy/alloy.log
```
