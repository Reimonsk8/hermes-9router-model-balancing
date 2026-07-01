#!/bin/bash
# Hermes 9Router - Metrics & Monitoring Setup
# Installs Alloy textfile collector, cron jobs, and metric exporters.
set -e

if [ -z "$GRAFANA_CLOUD_TOKEN" ] && [ ! -f /etc/alloy/config.alloy ]; then
  echo "ERROR: GRAFANA_CLOUD_TOKEN not set and no existing config found."
  echo "Usage: GRAFANA_CLOUD_TOKEN=glc_xxx bash setup/configure.sh"
  exit 1
fi

echo "=== Setting up textfile collector directory ==="
mkdir -p /var/lib/alloy/textfile
chmod 755 /var/lib/alloy/textfile

echo "=== Linking prom files ==="
ln -sf /var/lib/alloy/9router_metrics.prom /var/lib/alloy/textfile/9router_metrics.prom
ln -sf /var/lib/alloy/pihole_metrics.prom /var/lib/alloy/textfile/pihole_metrics.prom

echo "=== Installing Alloy config ==="
if [ -n "$GRAFANA_CLOUD_TOKEN" ]; then
  sed "s/\${GRAFANA_CLOUD_TOKEN}/$GRAFANA_CLOUD_TOKEN/g" \
    setup/alloy.config.alloy.template > /etc/alloy/config.alloy
  echo "Config generated from template with GRAFANA_CLOUD_TOKEN"
elif [ -f /etc/alloy/config.alloy ]; then
  cp /etc/alloy/config.alloy /etc/alloy/config.alloy.bak.$(date +%s)
  cp setup/alloy.config.alloy.template /etc/alloy/config.alloy
  echo "WARNING: Using template without token - edit /etc/alloy/config.alloy manually"
fi

echo "=== Adding cron jobs ==="
(crontab -l 2>/dev/null | grep -v "^#"; \
 echo "# Hermes metrics exporters"; \
 echo "*/15 * * * * cd /root/.hermes/scripts && python3 pihole_exporter.py >/dev/null 2>&1"; \
) | crontab -

echo "=== Restarting Alloy ==="
rc-service alloy restart 2>&1
echo "=== Done ==="
