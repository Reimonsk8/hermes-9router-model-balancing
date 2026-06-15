---
name: pihole-query-stats
description: Check Pi-hole ad-blocking stats from the FTL database when the web API is unavailable or returns 404.
---

# Pi-hole Query Stats via FTL Database

Use when `pihole status` works but `pihole api` endpoints return 404 or the web UI isn't accessible.

## Quick Reference

Pi-hole stores all queries in its FTL SQLite database at `/etc/pihole/pihole-FTL.db`.

### Schema

**query_storage** columns: `id`, `timestamp`, `type`, `status`, `domain`, `client`, `forward`, `additional_info`, `reply_type`, `reply_time`, `dnssec`, `list_id`, `ede`

### Status Codes (key ones)

| Code | Name | Meaning |
|---|---|---|
| 1 | GRAVITY | 📊 **Primary ad-block count** — blocked by gravity lists |
| 4 | REGEX | Blocked by regex rules |
| 17 | GRAVITY_CNAME | CNAME chain (not a true block, do NOT count as ad blocked) |
| 3 | CACHE | Served from cache |
| 14 | CACHE_STALE | Stale cache hit |
| 2 | FORWARDED | Forwarded to upstream |

### Key Stats via SQL

```sql
-- Total queries
SELECT COUNT(*) FROM query_storage;

-- Ads blocked (GRAVITY only — what the Pi-hole dashboard shows)
SELECT COUNT(*) FROM query_storage WHERE status = 1;

-- With domain names joined
SELECT qs.id, qs.timestamp, db.domain, cb.ip
FROM query_storage qs
LEFT JOIN domain_by_id db ON qs.domain = db.id
LEFT JOIN client_by_id cb ON qs.client = cb.id
WHERE qs.status = 1
ORDER BY qs.id DESC LIMIT 20;
```

### DB Path

Default: `/etc/pihole/pihole-FTL.db` (Alpine) or `/opt/pihole/pihole-FTL.db` (Debian/Raspberry Pi)

### Common Pitfalls

- **GRAVITY_CNAME (status=17)** is NOT an ad block — it's a CNAME chain lookup that happens after an initial query. Don't sum it with GRAVITY.
- The `counters` table uses sequential IDs (0, 1, …) with a numeric `value` column — no human-readable keys.
- Pi-hole API format: `http://pi.hole/api` (requires `pi.hole` DNS resolution; use `localhost` if no DNS entry).
