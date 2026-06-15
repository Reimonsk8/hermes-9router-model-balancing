---
name: messaging-platform-setup
description: "Diagnose, configure, and troubleshoot Hermes messaging platform integrations — WhatsApp, Telegram, Discord, Slack, Signal, Email, SMS, and more. Covers gateway setup, bridge/connector status, access control, session persistence, re-pairing, and common failure modes."
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [messaging, gateway, setup, troubleshooting, config]
---

# Messaging Platform Setup & Troubleshooting

Class-level umbrella skill for setting up and fixing messaging platform integrations in Hermes Agent.

## Scope

Covers the full lifecycle: initial setup, diagnostics, re-pairing, access control, and common failure modes across all supported gateway platforms — WhatsApp, Telegram, Discord, Slack, Signal, Email/SMTP, SMS (Twilio), Matrix, Mattermost, WeCom, Feishu, DingTalk, Weixin, BlueBubbles, QQBot, Yuanbao, and Google Chat.

Platform-specific quirks live in `references/`.

---

## Primary Diagnosis Checkpoints

Use this sequence whenever a platform "isn't working."

### 1. Confirm the gateway is running
```bash
hermes gateway status
ps aux | grep -i hermes  # gateway process + any bridge subprocesses
```
Gateway must be started before any platform will function. If not installed as a service, start it foreground:
```bash
hermes gateway
```

### 2. Check whether the gateway considers the platform "connected"
```bash
hermes platform                  # or: /platforms  in an active session
```
If a platform is absent here, Hermes will not route messages to/from it. The `send_message()` tool will return no targets for that platform.

### 3. Read the bridge logs
```bash
# WhatsApp (Baileys Node bridge):
cat ~/.hermes/logs/gateway.log   # WhatsApp events appear here
grep -A3 "listening\|connected\|ignored\|error" gateway.log | tail -30

# Core gateway log:
grep -i "<platform_name>" ~/.hermes/logs/gateway.log | tail -20
```
Look for:
- `"connected"` / `"online"` — bridge has established credentials
- `"ignored"` / `"rejected"` — access control or mode mismatch
- `"timeout"` / `"waiting"` — credentials pending, QR not scanned, token expired

### 4. Check .env environment variables
```bash
grep -i "PLATFORM_" ~/.hermes/.env   # e.g. WHATSAPP_, TELEGRAM_, DISCORD_
```
Every messaging platform uses env vars in `.env`. Key categories:
- **Enabled flag:** `PLATFORM_ENABLED=true/false`
- **Mode/strategy:** `PLATFORM_MODE=bot|self-chat|webhook` etc.
- **Access control:** `PLATFORM_ALLOWED_USERS=...`, `PLATFORM_ALLOWED_CHANNELS=...`
- **Auth tokens/keys:** `PLATFORM_BOT_TOKEN`, `PLATFORM_API_KEY`

### 5. Check config.yaml platform section
```bash
grep -A5 "^<platform>:" ~/.hermes/config.yaml
```
Even when env vars hold the auth, `config.yaml` can override behavior flags (e.g. `unauthorized_dm_behavior`, `reply_prefix`, `allowed_channels`).

---

## Platform-Specific Decision Trees

See `references/platforms/<name>.md` for the complete reference on: setup command, required env vars, access control, authenticated session management, and known pitfalls for each platform.

---

## Universal Pattern: "send_message() returns no targets"

This is the most common "not working" symptom. Route through these causes in order:

| Cause | Diagnostic | Fix |
|-------|-----------|-----|
| Gateway not running | `hermes gateway status` | `hermes gateway run` or `hermes gateway start` |
| Bridge not connected | Check platform log for "connected"/"ignored" | Re-run setup wizard; re-pair |
| Mode mismatch blocks messages | Log shows "rejected" by mode, not access | Change `PLATFORM_MODE` (e.g. `self-chat` → `bot`) |
| Access control rejects senders | Log shows `unauthorized` or `allowed_users` mismatch | Add sender's number to `PLATFORM_ALLOWED_USERS`; strip `+` from phone numbers |
| Session expired / unlinked | Re-pair flow required | `hermes <platform>` wizard again |

---

## Critical Config Patterns

### Access Control

**Phone numbers must be plain digits, no `+` or spaces:**
```
# Correct
TELEGRAM_ALLOWED_USERS=15551234567
# Wrong
TELEGRAM_ALLOWED_USERS=+15551234567  # ❌
# Wrong
TELEGRAM_ALLOWED_USERS=+1 (555) 123-4567  # ❌
```

**Allow-all shorthands exist on most platforms:**
```bash
WHATSAPP_ALLOWED_USERS=*            # allow everyone
WHATSAPP_ALLOW_ALL_USERS=true       # equivalent flag on WhatsApp/Signal
# OR remove both to use the DM pairing system (platform-specific)
```

Check the platform reference for the correct shorthand for the specific platform.

### Mode Selection

Several platforms have a "mode" env var that changes behavior fundamentally:
- **WhatsApp:** `WHATSAPP_MODE=bot` (forward all) or `WHATSAPP_MODE=self-chat` (self-talk only — rejects non-self, for testing only)
- **Slack:** public channels may need `message.channels` event subscription
- **Discord:** `require_mention` / `auto_thread` are config.yaml flags

Always check the mode first if messages are being ignoring or the channel appears connected but silent.

### Session Persistence

Bridge-based platforms (WhatsApp, Telegram, Signal, BlueBubbles) save credentials to a session directory. These DO survive restarts but DO need the directory to be writable and on a persistent volume (not tempfs):
```bash
# Check session dir exists
ls -la ~/.hermes/whatsapp/session/
ls -la ~/.hermes/telegram/session/
```

Degraded sessions or stale credentials are the #2 cause of "suddenly stopped working" after a bridge reconnect.

---

## Re-pairing / Re-authentication

When a session breaks (phone reset, WhatsApp update, manually unlinked, token expired):

```bash
# Generic
hermes <platform>      # scans QR code, saves new session, exits cleanly

# Then restart the gateway
hermes gateway restart
```

If the QR code is garbled, verify terminal is at least 60 columns wide and supports Unicode. QR codes expire every ~20 seconds — rerun if it times out.

---

## Configuring Platform Behavior Flags

Behavior defaults are set in the platform section of `config.yaml`. Examples:

```yaml
whatsapp:
  unauthorized_dm_behavior: ignore   # silently drop unauthorized DMs
  reply_prefix: ""                    # disable ⚕ Hermes Agent header

telegram:
  require_mention: true               # bot only responds when @mentioned
  allowed_chats: ""                   # restrict to specific chat IDs

discord:
  require_mention: true
  auto_thread: true
  reactions: true
```

Application: `hermes config edit` → find the platform section → add/change keys. Some changes require a gateway restart.

---

## Troubleshooting Reference

### "Gateway dies on SSH logout"
```
sudo loginctl enable-linger $USER
```

### "Windows: Node.js not installed but `node` works in terminal"
macOS launchd doesn't inherit shell PATH. The fix depends on the platform; for subscription-based platforms the bridge may start from schedule. Reinstall the gateway after fixing PATH so it picks up the correct PATH snapshot.

### "Messages not received but bridge connected"
1. Check `PLATFORM_ALLOWED_*` env var — sender number not in list?
2. Check `WHATSAPP_DEBUG=true` — more detail in bridge-log
3. Check `CHANNEL_PROMPTS` in `config.yaml` for any prompt overriding behavior

### "Bridge crashes or reconnect loops"
Update Hermes and re-pair. Bridge crashes almost always mean the protocol changed.

### CLI Output & Aesthetics
For consistent, legible output in messaging or terminal helper scripts, use standardized banners.
```python
def beautiful_print(message):
    print("*" * 50)
    print(f"  {message}")
    print("*" * 50)
```
See `references/cli-output-formatting.md`.

---

## Setup Wizard

```bash
hermes gateway setup              # Interactive: configure all platforms
hermes <platform>                 # Platform-specific pairing (shows QR etc.)
```

Supported platforms: telegram, discord, slack, whatsapp, signal, email, sms (twilio), matrix, mattermost, dingtalk, feishu, wecom, weixin, bluebubbles, qqbot, yuanbao, google_chat, irc, line, ntfy, simplex, teams

Documentation: https://hermes-agent.nousresearch.com/docs/user-guide/messaging/
