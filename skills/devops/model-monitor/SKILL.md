---
name: model-monitor
description: "Skills and scripts for monitoring LLM usage metrics dynamically in Hermes."
---

# Model Monitor Skill

This skill provides the structure and scripts for monitoring LLM model usage dynamically rather than relying on hardcoded lists.

### Sorting and Ordering
- **Ordering**: When displaying token usage, prioritize models with defined limits (sorted by consumption percentage) followed by models without limits. Use a tuple-based key for sorting: `(m['limit'] is None, m['pct'])` to ensure unconfigured models appear at the end.
- **Dynamic Discovery**: Always parse `~/.hermes/config.yaml` to retrieve the active model chain rather than using hardcoded lists.
- **Reporting**: When reporting token usage, always include a calculated total across all models to provide a clear view of overall consumption. (See `references/reporting-checklist.md`)

### Monitoring Cluster: Observability & Health
This umbrella covers monitoring tools for Hermes infrastructure, including LLM usage, server health (Alloy), and network stats (Pi-hole).

#### Pi-hole Query Stats
Use when `pihole status` works but `pihole api` endpoints return 404. Pi-hole stores all queries in its FTL SQLite database at `/etc/pihole/pihole-FTL.db`.
- **Status 1**: GRAVITY (Primary ad-block)
- **Status 17**: GRAVITY_CNAME (Do NOT count as ad-block)

#### Grafana Alloy Monitoring
Deploy Grafana Alloy on standalone Linux (especially Alpine) for metrics + logs scraping. successor to Grafana Agent.
- **Metrics**: node_exporter-style (`node_cpu_seconds_total`, etc.)
- **Logs**: Journal as JSON.




## References

- `scripts/context_exporter.py`: Exports context window usage metrics (used, max, remaining, utilization) to Prometheus format.
- `scripts/update_all_metrics.sh`: Unified script to run all monitoring tasks (auto-balance, Pi-hole, context).
- **Pitfall**: When adding metrics files to Alloy/Prometheus, ensure the file path is explicitly added to the `local.file_match` targets in `config.alloy` and that the service is restarted (`rc-service alloy restart` on Alpine) for changes to take effect.
