# Agent Onboarding

Read this on cold start when operating from the Searchpo `skills/` directory.

## What Lives Here

```text
skills/
  RESOLVER.md                 # skill dispatcher
  _AGENT_README.md            # this directory contract
  <skill>/SKILL.md            # skill workflow and metadata
```

Each `SKILL.md` keeps Codex-compatible `name` and `description` fields, plus Searchpo routing metadata (`triggers`, `tools`, `mutating`) for local plugin checks.

## Routing

Parse every `skills/*/SKILL.md` frontmatter block and match the inbound request against `description` and `triggers`. Substring matching is the baseline. Semantic matching is allowed, but the matched skill body must be read before acting.

Do not treat `.claude/skills/` or `.codex/skills/` as source. They are generated mirrors.

## Updating

After editing a skill, resolver, or plugin manifest:

```bash
npm run skills:sync
npm run skills:check
```

If a generated bridge differs, fix the source under `skills/` and regenerate the bridge.
