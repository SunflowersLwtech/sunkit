# Agent Skill Directory Contract

This directory is the agent-readable skill surface for the bundle. Read this
file on cold start, then read `RESOLVER.md`, then read the matching
`SKILL.md`.

## What Lives Here

```text
skills/
  _AGENT_README.md
  RESOLVER.md
  github-repo-to-x-threads/
    SKILL.md
    scripts/
    references/
```

The skill directory is canonical. Root plugin manifests, `commands/`,
`.claude-plugin/`, `.codex-plugin/`, `.claude/`, and `.agents/` are adapters or
generated install surfaces.

## Routing

For any request involving technical sources, Agent engineering account
positioning, support/KYC complaint rewrites, or X/Twitter copy, read
`skills/github-repo-to-x-threads/SKILL.md` before acting. That includes GitHub
repos, local repos, papers, alphaXiv/arXiv URLs, blog/docs URLs, PDFs, notes,
raw ideas, bio/pinned-post work, bug-report rewrites, posting-pack review,
image generation for a posting pack, official X API publishing, metrics
capture, or skill-evolution feedback.

## Operating Rules

- Keep public claims separated as verified source facts, live metadata,
  reasonable inference, or user vision.
- Keep the main account focused on Agent engineering: reliability,
  build-in-public, paper-to-system, and embodied AI watch.
- Convert KYC/support/life/media noise into professional bug reports,
  Agent failure-mode notes, or off-main-account drafts.
- Generated images are conceptual unless they are actual repo/user assets.
- Do not use disposable mock/fallback artifacts as a substitute for the real
  deliverable. If actual images, the configured install path, live metadata, or
  official publish credentials are required and unavailable, mark that gate
  blocked instead of producing a throwaway stand-in.
- Store governed run outputs under ignored `repo-to-x-workspace/`.
- Use official X API publishing only after explicit user approval and OAuth2
  user credentials.
- Never commit `.env`, tokens, cloned repos, generated images, or run outputs.
