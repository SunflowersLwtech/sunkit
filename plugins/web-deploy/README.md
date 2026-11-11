# web-deploy

Deploy web apps through APIs and GitHub Actions instead of clicking a dashboard —
and prove what is actually live instead of trusting a green checkmark.

Four providers, one lesson each:

- **Vercel** — env vars and deployment state from the REST API; `NEXT_PUBLIC_*`
  does nothing until the next build; Next's undocumented version-skew protection
  is already there, and `deploymentId` re-downloads every static asset.
- **GitHub Actions → Vercel** — the one-token bootstrap (`VERCEL_TOKEN`,
  `VERCEL_ORG_ID` org secrets, `VERCEL_PROJECT_ID` per repo,
  `git.deploymentEnabled=false`), so teammates deploy by pushing and never
  touch Vercel.
- **Render** — GHCR-image services without Render's GitHub connection: CI builds
  and pushes an image tagged with the commit (`RELEASE_SHA` baked in), deploys
  are commit-tagged, never `:latest`; `scripts/render.sh` is the fallback when
  CI or local Docker is down, including a native remote-build fallback over SSH.
- **Supabase** — migration-ledger repair when the ledger lies, one-off SQL fixes,
  and going through the Management API when a repo is not linked.

## Install

```
/plugin marketplace add SunflowersLwtech/sunkit
/plugin install web-deploy@sunkit
```

## Needs

- `vercel` CLI and a `VERCEL_TOKEN` env var (never in argv) for the Vercel paths.
- `gh` and `jq` for `scripts/render.sh`; `RENDER_API_KEY`, `RENDER_OWNER_ID`,
  `RENDER_REGISTRY_CRED` env vars; the Render registry lives in `services.json`
  (a placeholder example ships with the plugin).
- `supabase` CLI for the Supabase paths.

Read `skills/web-deploy/SKILL.md` first; the long measured bodies are in
`skills/web-deploy/references/`.
