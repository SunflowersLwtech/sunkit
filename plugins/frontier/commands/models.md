---
description: List the models the magpie gateway serves and the harness subagents, optionally filtered (e.g. /frontier:models gpt)
---

Harness subagents (agy-pro, agy-trial, zcode, zen, frontier) and where each runs:

!`harness-run list`

Models the gateway serves, filtered by "$ARGUMENTS":

!`harness-run models $ARGUMENTS`

Show both lists to the user compactly. In a claude-gw session they can switch with `/model <id>`; any session can hand a task to one of these models through the frontier subagent.
