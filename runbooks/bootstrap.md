# Bootstrap Runbook

After scaffolding this skillpack into an agent workspace:

1. Read `AGENTS.md`.
2. Read `INSTALL_FOR_AGENTS.md`.
3. Read `skills/_AGENT_README.md`.
4. Read `skills/RESOLVER.md`.
5. For any matching request, read
   `skills/github-repo-to-x-threads/SKILL.md` before acting.

Optional local credentials belong in an ignored `.env`, copied from
`skills/github-repo-to-x-threads/.env.example`.

Before saying the bundle is ready after edits, run:

```bash
python3 -m compileall skills/github-repo-to-x-threads/scripts
bash -n scripts/install_skill_bundle.sh scripts/sync_clean_external.sh
python3 -m json.tool skills/manifest.json >/dev/null
python3 -B skills/github-repo-to-x-threads/scripts/run_repo_to_x_pack.py . \
  --run-id smoke-agent-plugin-refactor --refresh
scripts/install_skill_bundle.sh /Users/sunfl/Documents/media/X
```
