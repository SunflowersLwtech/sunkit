---
name: searchpo-agent-capabilities
description: Use when Searchpo agents need to inspect available .env keys, provider/API capabilities, DeepWiki MCP availability, credential routing, side-effect boundaries, or decide which agent should use which external service without exposing secrets.
version: 1.0.0
triggers:
  - ".env"
  - "API keys"
  - "agent capabilities"
  - "credential routing"
  - "provider keys"
  - "DeepWiki MCP availability"
  - "能力清单"
  - "密钥路由"
tools:
  - shell
  - filesystem
mutating: false
---

# Searchpo Agent Capabilities

Use this skill to let Searchpo agents organize available credentials and MCP services without leaking secrets.

## Source Of Truth

- Capability catalog: `config/agent_capabilities.json`
- Safe reporter: `scripts/agent_capabilities.py`
- Project MCP config: `.mcp.json`
- Real secret values: `.env` only; never print, copy, or persist values.

## Workflow

1. Run the redacted reporter before choosing external services:

```bash
python3 scripts/agent_capabilities.py --profile all --format text
```

Use narrower profiles when possible: `research`, `repo`, `paper`, `implementation`, `provider`, `render`, `lambda`, `publish`, or `live`.

2. Route work by owner:
   - `searchpo-research-agent`: DeepWiki MCP, GitHub/GitLab/source APIs, AnySearch and supplemental research, social/web source context.
   - `searchpo-impl-agent`: DeepSeek, Gemini, Remotion, Lambda, Douyin adapter/upload execution.
   - `searchpo-main-agent`: command profile selection, side-effect boundary, notification, final release decision.

3. Treat `status=available` as permission to use a capability only inside the existing Searchpo gate model. Live publishing still requires an explicit current-run user request.
4. If a required capability is unavailable, fail at the relevant gate and report the missing key names only.

## Safety Rules

- Printing key names is allowed; printing values is not.
- Do not move credentials into skill files, generated agent files, runtime artifacts, or Git-tracked docs.
- Do not let optional model-provider keys bypass source evidence, FactBank, cross-check, media audit, or publish verification.
- Use `.env.example` only as a variable-name reference; it must not contain real values.
