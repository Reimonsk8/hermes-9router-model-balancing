#!/usr/bin/env python3
import os
import sqlite3

PIHOLE_DB = "/etc/pihole/pihole-FTL.db"
PROM_OUTPUT = "/var/lib/alloy/pihole_metrics.prom"


def export_pihole_metrics(db_path: str = PIHOLE_DB, output_path: str = PROM_OUTPUT):
    if not os.path.exists(db_path):
        print(f"Pi-hole DB not found: {db_path}")
        return

    try:
        conn = sqlite3.connect(db_path)
        c = conn.cursor()

        c.execute("SELECT COUNT(*) FROM queries")
        total = c.fetchone()[0]

        c.execute("SELECT COUNT(*) FROM queries WHERE status IN (1,2,3)")
        blocked = c.fetchone()[0]

        c.execute("SELECT COUNT(*) FROM queries WHERE timestamp > (SELECT unixepoch('now', '-15 minutes'))")
        last_15m_total = c.fetchone()[0]

        c.execute(
            "SELECT COUNT(*) FROM queries "
            "WHERE status IN (1,2,3) AND timestamp > (SELECT unixepoch('now', '-15 minutes'))"
        )
        last_15m_blocked = c.fetchone()[0]

        conn.close()

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "w") as f:
            f.write("# HELP pihole_total_queries Total DNS queries (cumulative)\n")
            f.write("# TYPE pihole_total_queries counter\n")
            f.write(f"pihole_total_queries {total}\n")

            f.write("# HELP pihole_blocked_queries Total blocked DNS queries (cumulative)\n")
            f.write("# TYPE pihole_blocked_queries counter\n")
            f.write(f"pihole_blocked_queries {blocked}\n")

            f.write("# HELP pihole_queries_last_15m DNS queries in last 15 minutes\n")
            f.write("# TYPE pihole_queries_last_15m gauge\n")
            f.write(f"pihole_queries_last_15m{{type=\"total\"}} {last_15m_total}\n")
            f.write(f"pihole_queries_last_15m{{type=\"blocked\"}} {last_15m_blocked}\n")
    except Exception as e:
        print(f"Error exporting Pi-hole metrics: {e}")


if __name__ == "__main__":
    export_pihole_metrics()
