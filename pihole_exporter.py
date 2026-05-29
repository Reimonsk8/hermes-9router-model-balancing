#!/usr/bin/env python3
import sqlite3

def export_pihole_metrics():
    db_path = "/etc/pihole/pihole-FTL.db"
    try:
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM queries WHERE status IN (1,2,3)")
        blocked = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM queries")
        total = c.fetchone()[0]
        conn.close()
        
        with open("/var/lib/alloy/pihole_metrics.prom", "w") as f:
            f.write("# HELP pihole_blocked_queries Total blocked DNS queries\n")
            f.write("# TYPE pihole_blocked_queries gauge\n")
            f.write(f"pihole_blocked_queries {blocked}\n")
            f.write("# HELP pihole_total_queries Total DNS queries\n")
            f.write("# TYPE pihole_total_queries gauge\n")
            f.write(f"pihole_total_queries {total}\n")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    export_pihole_metrics()
