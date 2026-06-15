# WhatsApp

## Setup Commands

```bash
hermes whatsapp                          # Pair / re-pair (shows QR code)
hermes gateway setup  # → select WhatsApp from list
```

## Required Env Vars (~/.hermes/.env)

```bash
WHATSAPP_ENABLED=true
WHATSAPP_MODE=bot          # bot mode: forwards all user message to Hermes
                            # self-chat mode: only user's own self-chat; rejects all non-self DMs; testing only
# Access control — pick ONE:
WHATSAPP_ALLOWED_USERS=15551234567          # comma-separated, plain digits, no +
WHATSAPP_ALLOWED_USERS=*                   # allow everyone (equivalent to WHATSAPP_ALLOW_ALL_USERS=true)
# WHATSAPP_ALLOW_ALL_USERS=true             # Another shorthand; same as *
```

## Session Directory

```
~/.hermes/whatsapp/session/    # Baileys Qtum + auth tokens — protect like a password
```

Sessions survive restarts automatically. Do not share or commit this directory.

## Bridge Mode: bot vs self-chat

| Mode | Behavior | When to use |
|------|----------|-------------|
| `bot` | Forwards all allowed senders to agent; replies routed back | Production, multi-user, dedicated number |
| `self-chat` | Ignores all non-self messages; only user→self is allowed | Personal testing, single-user scratchpad |

**Switch from self-chat to bot:** edit `.env`, set `WHATSAPP_MODE=bot`, then `hermes gateway restart`.

## Phone Number Format Gotcha

`WHATSAPP_ALLOWED_USERS` must be **plain digits only**:
```
WRONG: +526462763784    # contains +   → rejected
WRONG: 526462763784     # missing country code context may still work but align with Baileys format
RIGHT: 526462763784     # plain digits (or separated by comma: "15551234567,52966888144")
```

If numbers are partially masked in the `.env` comment (e.g., `+526****3784`), that works as a comment only. The active value must be plain digits.

## Log Patterns

```
✅ WhatsApp connected!                   = bridge is healthy
listening on port 3000 (mode: self-chat) = unused self-chat mode
listening on port 3000 (mode: bot)      = bot mode active
self_chat_mode_rejects_non_self         = wrong mode for real users
Timeout in AwaitingInitialSync           = bridged timed out; gateway timeouts out
```

## Re-pairing

If bridge keeps dropping or `bridge.log` shows `"connection timeout"` or `"disconnected"` without reconnecting:
```bash
hermes whatsapp         # Fresh QR scan
hermes gateway restart   # Pick up new session
```

## Known Pitfalls

- **`WHATSAPP_MODE=self-chat` is the default and silently discards all non-self DMs.** Diagnosed by bridge log event `"ignored"` with reason `self_chat_mode_rejects_non_self`.
- **Access control / allowed users mismatch** — sender's phone number must match exactly (digits, no `+`, no spaces), or use `*` for all.
- **`WHATSAPP_ALLOWED_USERS=+526****3784` (masked value) in an active line** results in an invalid match; only use full plain-digit numbers for active allowed users.
- **Formatted/partial numbers in comments** (lines starting with `#`) are irrelevant; the active `WHATSAPP_ALLOWED_USERS=` line is what matters.
- **Session directory on tmpfs or cleared container** — if `~/.hermes/whatsapp/session/` disappears, reset will require re-scan.
- **QR code expires in ~20 seconds** during pairing — rerun wizard if it times out.
- **Terminal <60 cols** renders garbled QR — widen terminal before `hermes whatsapp`.
