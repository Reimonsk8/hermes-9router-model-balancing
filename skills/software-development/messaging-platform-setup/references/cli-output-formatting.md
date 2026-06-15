---
name: cli-output-formatting
description: Use when needing consistent, legible output for CLI scripts. Provides patterns for styled banners and logs.
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [cli, formatting, scripts, aesthetics]
    related_skills: [hermes-agent-skill-authoring]
---

# CLI Output Formatting

## Overview
Standardized formatting for CLI-based agent responses and scripts. Ensures consistency and readability across terminal sessions.

## When to Use
- Creating helper scripts (e.g., in `~/.hermes/scripts/`) that need to output status or results.
- Formatting agent text responses to be distinct from system noise.

## Styles and Patterns

### Beautiful Banners
For section headers or script status:

```python
def beautiful_print(message):
    print("*" * 50)
    print(f"  {message}")
    print("*" * 50)
```

## Common Pitfalls
- Overusing headers in automated logs; keep them concise so they don't flood the terminal.
- Hardcoding widths that exceed standard terminal width (default to 50-80 chars).

## Verification Checklist
- [ ] Output is legible in a standard terminal.
- [ ] Banners are distinguishable from standard log output.
