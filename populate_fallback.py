#!/usr/bin/env python3
"""Populate config.yaml fallback_providers from 9router DB models."""
import sqlite3
import yaml

CONFIG_PATH = "/root/.hermes/config.yaml"
DB_PATH = "/root/.9router/db/data.sqlite"

with open(CONFIG_PATH, "r") as f:
    config = yaml.safe_load(f)

conn = sqlite3.connect(DB_PATH)
rows = conn.execute("SELECT DISTINCT provider, model FROM usageHistory ORDER BY model").fetchall()
conn.close()

providers = []
for provider, model in rows:
    entry = {"provider": provider, "model": model}
    if entry not in providers:
        providers.append(entry)

if not providers:
    print("No models found in 9router DB")
else:
    config["fallback_providers"] = providers
    with open(CONFIG_PATH, "w") as f:
        yaml.safe_dump(config, f, default_flow_style=False)
    print(f"Populated fallback_providers with {len(providers)} models:")
    for p in providers:
        print(f"  {p['provider']}/{p['model']}")
