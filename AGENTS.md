# Repository Instructions

## Shape

- This repository is an agent skillpack/plugin bundle in the style of an
  agent-first project: root protocol files, canonical skills, and thin adapter
  manifests.
- Agent entrypoints are `AGENTS.md`, `llms.txt`, `INSTALL_FOR_AGENTS.md`,
  `CLAUDE.md`, `skills/_AGENT_README.md`, and `skills/RESOLVER.md`.
- Distribution manifests are `skillpack.json`, `openclaw.plugin.json`,
  `.codex-plugin/plugin.json`, and `.claude-plugin/plugin.json`.

## Source Of Truth

- Keep the canonical reusable skill under `skills/github-repo-to-x-threads/`.
- Keep shared agent routing docs under `skills/RESOLVER.md` and
  `skills/_AGENT_README.md`, with `skills/manifest.json` as the machine-readable
  skill index.
- Keep `.codex-plugin/`, `.claude-plugin/`, `commands/`, `.agents/`,
  `.claude/`, and `plugins/` as adapters or generated install surfaces only.
- The project-level Codex marketplace must point at
  `plugins/github-repo-to-x-threads/`, a generated real-file adapter. Do not use
  symlinks there; Codex installs an empty cache when the adapter is symlink-only.
- Do not move core skill instructions or helper scripts into `.claude/` as the primary source.

## Agent Read Order

1. Read `AGENTS.md`.
2. Read `INSTALL_FOR_AGENTS.md` for install and verification protocol.
3. Read `skills/_AGENT_README.md` for the scaffolded-skill contract.
4. Read `skills/RESOLVER.md` to route the request.
5. Read `skills/github-repo-to-x-threads/SKILL.md` before doing posting-pack
   work.

## Safety

- Never commit `.env`, tokens, cloned third-party repos, generated run workspaces, or generated image files.
- Treat all public X copy as claim-sensitive: verified repo facts, live metadata, inference, and user vision must stay separated.
- Generated images are conceptual unless they are actual repo/user assets and must be registered in `images_manifest.json`.
- Use official X API publishing only with explicit user approval and OAuth2 user credentials; never add cookie/session/proxy-based posting as a default path.
- Treat GPT Image 2 / image2 / 配图 requests as a native image-generation requirement, not as permission to generate placeholder diagrams with scripts.
- Do not use disposable mocks, throwaway fallback paths, prompt-only stand-ins,
  or temporary install targets as proof that a required artifact or validation
  succeeded. If the requested real target cannot be written, generated,
  inspected, or published, report the real blocker and stop that gate.
- Prompt-only output is allowed only when the user explicitly requested prompts
  as the deliverable. It is never a fallback for failed image generation and
  never makes an actual-image posting pack ready.
- Do not validate required local adapters by installing to `/tmp` or another
  substitute target. `scripts/install_skill_bundle.sh /Users/sunfl/Documents/media/X`
  must succeed for that verification gate; otherwise the gate is blocked.

## Verification

- Run Python syntax checks for scripts after editing.
- Run a smoke `run_repo_to_x_pack.py` workspace creation before publishing packaging changes.
- Run `scripts/install_skill_bundle.sh /Users/sunfl/Documents/media/X` when validating local Claude/Codex adapters.
- Validate JSON manifests after edits: `.codex-plugin/plugin.json`,
  `.claude-plugin/plugin.json`, `skillpack.json`, and `openclaw.plugin.json`.
