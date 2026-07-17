# Installation Guide For Agents

Read this file before installing or operating the bundle. This repository is an
agent skillpack/plugin, not an app server. The canonical behavior lives in
`skills/github-repo-to-x-threads/`; root manifests and adapter folders only make
that skill visible to different agent runtimes.

## Step 0: Read Order

1. `AGENTS.md` - repository rules, safety gates, and source-of-truth policy.
2. `skills/RESOLVER.md` - route the user's request to the right skill surface.
3. `skills/_AGENT_README.md` - cold-start contract for scaffolded skills.
4. `skills/github-repo-to-x-threads/SKILL.md` - the full workflow.
5. `README.md` - human-facing usage and maintenance notes.

Claude Code can also start from `CLAUDE.md`, which points back to this same
protocol.

## Step 1: Install Local Agent Surfaces

From the repository root:

```bash
scripts/install_skill_bundle.sh /Volumes/T7/media/X
```

The installer keeps these as canonical or distributable surfaces:

- `skills/github-repo-to-x-threads/`
- `skills/RESOLVER.md`
- `skills/_AGENT_README.md`
- `skills/manifest.json`
- `.codex-plugin/plugin.json`
- `.claude-plugin/plugin.json`
- `commands/github-repo-to-x-threads.md`
- `skillpack.json`
- `openclaw.plugin.json`
- `llms.txt`
- `INSTALL_FOR_AGENTS.md`
- `CLAUDE.md`

It also writes user-level Codex and Claude Code skill copies for local use. Do
not copy the whole repo into `.claude/skills`; `.claude/` is a generated adapter
surface.

For project-level Codex plugin recognition, the installer also writes:

- `.agents/plugins/marketplace.json`
- `plugins/github-repo-to-x-threads/.codex-plugin/plugin.json`
- `plugins/github-repo-to-x-threads/skills/github-repo-to-x-threads/SKILL.md`
- `plugins/github-repo-to-x-threads/commands/github-repo-to-x-threads.md`

`plugins/github-repo-to-x-threads/` must contain real copied files, not only
symlinks. Codex can list a symlink-only plugin but installs an empty cache.
Codex Desktop currently does not expose packaged `commands/*.md` files as
custom slash-menu entries; install success should be validated through plugin
and skill loading, not by expecting `/github-repo-to-x-threads` in the picker.
Invoke the workflow in Codex with natural language, or name the skill explicitly
as `$github-repo-to-x-threads`.

Register or refresh the project marketplace from the real project root:

```bash
CODEX_CLI="${CODEX_CLI_PATH:-/Applications/Codex.app/Contents/Resources/codex}"
"$CODEX_CLI" plugin marketplace list
"$CODEX_CLI" plugin marketplace add /Volumes/T7/media/X   # only if media-x-local is absent
"$CODEX_CLI" plugin add github-repo-to-x-threads@media-x-local
scripts/verify_codex_project_plugin.sh .
```

After changing the plugin manifest or skill instructions, bump the Codex
cachebuster before reinstalling:

```bash
python3 /Users/chenyu/.codex/skills/.system/plugin-creator/scripts/update_plugin_cachebuster.py .
scripts/install_skill_bundle.sh /Volumes/T7/media/X
CODEX_CLI="${CODEX_CLI_PATH:-/Applications/Codex.app/Contents/Resources/codex}"
"$CODEX_CLI" plugin add github-repo-to-x-threads@media-x-local
scripts/verify_codex_project_plugin.sh .
```

## Step 2: Configure Optional Credentials

No credentials are required for manual-safe drafting. For live metadata,
pre-publish evaluation, or official X API publishing, create a local ignored
`.env`:

```bash
cp skills/github-repo-to-x-threads/.env.example .env
```

Set only the credentials needed for the run:

- GitHub metadata: `GH_TOKEN`, `GITHUB_TOKEN`, or `GITHUB_PERSONAL_ACCESS_TOKEN`.
- Grok/xAI evaluation: `GROK_API_KEY`.
- Official X API publishing: OAuth2 user credentials with
  `tweet.read users.read tweet.write media.write offline.access`.

Never commit `.env` or tokens.

## Step 3: Run The Skill

For a GitHub repo or local repo:

```bash
python3 -B skills/github-repo-to-x-threads/scripts/run_repo_to_x_pack.py \
  https://github.com/owner/repo --refresh
```

For a paper, web URL, PDF, note, existing posting pack, or raw idea:

```bash
python3 -B skills/github-repo-to-x-threads/scripts/run_any_to_x_pack.py \
  "https://example.com/source" \
  --prompt "create a responsible X posting pack"
```

Outputs belong under the ignored local workspace:

```text
repo-to-x-workspace/runs/<run-id>/
```

Generated images must be actual native image-generation assets by default,
stored under the run directory, and registered in `images_manifest.json`.
Prompt-only entries are not a fallback. Use them only when the user explicitly
asked for prompt-only/text-only/manual-image output. If an actual-image pack is
required and the image tool cannot provide a governable file, the image gate is
blocked; do not replace it with prompts.

## Step 4: Publish Only With Explicit Approval

Default mode is `manual-safe`: produce a paste-ready pack and let the user
publish manually.

Use `official-api-publish` only when the user explicitly approves live CLI
posting and OAuth2 user credentials are configured. Never add or use
cookie/session/proxy-based X posting as the default path.

## Step 5: Verify Before Shipping Changes

Run these checks after editing scripts, manifests, install surfaces, or the
canonical skill:

```bash
python3 -m compileall skills/github-repo-to-x-threads/scripts
bash -n scripts/install_skill_bundle.sh scripts/sync_clean_external.sh
bash -n scripts/verify_codex_project_plugin.sh
python3 -m json.tool .codex-plugin/plugin.json >/dev/null
python3 -m json.tool .claude-plugin/plugin.json >/dev/null
python3 -m json.tool skillpack.json >/dev/null
python3 -m json.tool openclaw.plugin.json >/dev/null
python3 -m json.tool skills/manifest.json >/dev/null
python3 -B skills/github-repo-to-x-threads/scripts/run_repo_to_x_pack.py . \
  --run-id smoke-agent-plugin-refactor --refresh
scripts/verify_codex_project_plugin.sh .
scripts/install_skill_bundle.sh /Volumes/T7/media/X
"${CODEX_CLI_PATH:-/Applications/Codex.app/Contents/Resources/codex}" plugin add github-repo-to-x-threads@media-x-local
scripts/verify_codex_project_plugin.sh .
```

Do not substitute `/tmp` or another disposable destination for the install
verification above. If `/Volumes/T7/media/X` is not writable, report
the permission blocker; the adapter-install gate has not passed.

Keep `repo-to-x-workspace/` ignored after smoke runs.
