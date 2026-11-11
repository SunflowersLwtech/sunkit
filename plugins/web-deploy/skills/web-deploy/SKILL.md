---
name: web-deploy
description: Deploy a web app to Vercel or Render and read/write its deployment env vars through APIs and GitHub Actions instead of clicking a dashboard. Covers the one-token Vercel + GitHub Actions setup (org-level secrets, per-repo project id, turning off Vercel's native Git auto-deploy), the Vercel REST API for env vars and deployment state, Render's GHCR-image services, Supabase migration-ledger repair, and proving the live site is the commit you pushed. Use for "deploy this", "ship the web app", "set an env var on Vercel", "the site still shows the old build", "the CI deploy is failing", "rotate the deploy token", and 「部署到 Vercel」「加个环境变量」「上线了吗」「CI 部署挂了」「换个 token」.
---

# Deploying web apps (Vercel · Render · GitHub Actions)

## Pushing to `main` is often the production deploy

In a bootstrapped repo, `.github/workflows/deploy.yml` fires `on: push: branches: [main]`
and ends in `vercel deploy --prebuilt --prod`. There is no separate "release" step to
forget — the push *is* the release. Look before you push:

```bash
ls .github/workflows/ && sed -n '1,10p' .github/workflows/deploy.yml
```

Ask a human first for: rotating or replacing a deploy token, deleting or overwriting an
existing env var, the first production deploy of a project nobody has shipped yet, and
anything that changes what a live domain serves. These are outward-visible and cheap to
ask about, expensive to undo.

## Find the repo's one deploy path — do not guess it

Three shapes, mutually exclusive on purpose:

| Shape | How you tell | How it deploys |
|---|---|---|
| GitHub Actions → Vercel | `.github/workflows/deploy.yml` **and** `vercel.json` with `git.deploymentEnabled=false` | push to `main`, or `gh workflow run deploy.yml`. Watch the Actions run, not the Vercel dashboard |
| Vercel CLI, prebuilt | `.vercel/project.json` present, no deploy workflow | `vercel build --prod` then `vercel deploy --prebuilt --prod --scope <slug>`. It uploads the **local** output, so commit first or you ship uncommitted work. It also replaces the whole live site with your tree: when other sessions deploy the same project, build from a fresh `origin/main` and first compare the live copy of every file `git diff --name-only <live commit> origin/main -- <site dir>` names with your tree; a live file you don't have means someone shipped after your base, and deploying rolls it back |
| Render, GHCR image | the service is in `services.json` | push to `main`; the repo's own CI builds and pushes the image. `bash scripts/render.sh release <service>` is the fallback for when CI is unavailable |

`git.deploymentEnabled=false` is not decoration: it stops Vercel's native Git integration
from racing the workflow. Where it is missing, one push produces two deployments and
"which build is live" stops having an answer.

## Env vars and deployment state: the API, not the dashboard

Both ids the Vercel API needs are in the repo's `.vercel/project.json`; the read, create
and "what actually deployed" calls are in `references/vercel.md`. Three things that
decide whether the work lands:

- **`NEXT_PUBLIC_*` is inlined at build time.** Creating one on Vercel changes nothing on
  the live site until the next build. This is the usual reason "I set it and nothing
  happened". Redeploy, then check the newest deployment's timestamp is *after* the env
  var's creation.
- **Keep the value out of argv and history.** Build the request body with `python3`
  reading from the environment (`references/vercel.md`); pipe secrets into
  `gh secret set`, never pass them as an argument. Do not print or commit a token value.
- **A `vercel whoami` scope error is not "you are logged out".** It can name the personal
  Hobby team while the REST token works fine — see `references/vercel.md` before
  concluding you need to re-authenticate.

## Green CI is not "shipped" — name the observable

- **Vercel:** read `state`, `target` and `url` of the newest deployment from the
  deployments API (`references/vercel.md`). A `READY` build proves a build ran, not that
  it contains your commit.
- **Render:** the image bakes `RELEASE_SHA`, so *"the deploy succeeded"* and *"the live
  commit is the one I pushed"* are two separate assertions. Read the service's health
  endpoint and compare its release field.
- **Deploy the commit-tagged image, never `:latest`.** `render.sh release` does this
  deliberately: `:latest` moves under you and makes "which commit is live?" unanswerable
  from the Render side.
- After any infra change, say what you verified and what you only assumed. A created env
  var is not a live feature until a build consumed it.

## Traps that look like something else

1. **`vercel pull` sees an empty `VERCEL_TOKEN` / `VERCEL_ORG_ID` in Actions.** GitHub
   Free does not expose organization-level secrets to private repos. Mirror those two as
   repo secrets; this is not a bad token.
2. **A Vercel CLI OAuth login token cannot mint a long-lived token through the API.**
   Long-lived deploy tokens come from the Dashboard → Account Settings → Tokens page.
3. **A Render build refusing a dirty tree is the design, not a failure.** An image tagged
   with a commit must contain that commit; commit or stash and rebuild.
4. **A Supabase migration divergence is usually a bookkeeping lie, not a real one.** Diff
   the files and check whether the objects actually exist before working around it —
   `references/supabase.md` has the case where months of avoiding `db push` were
   unnecessary. `repair` writes only to `schema_migrations` and re-runs no DDL.
5. **Next already ships version-skew protection, undocumented.** Before building a
   stale-client fix, check for the build id in the RSC payload
   (`references/vercel.md`); setting `deploymentId` *replaces* it and re-downloads every
   static asset each deploy — measured at ~313 KB per returning visitor per deploy on a
   real Next.js app, several deploys a day, to fix nothing.

## Files here, and when to open them

Long measured bodies live in `references/` — read one when you are about to act on it,
not on every trigger.

- `references/vercel.md` — before any env var read/write, before asking "what actually
  deployed", before a stale-client fix.
- `references/github-actions.md` — only when bootstrapping a repo, rotating a deploy
  token, or a CI deploy is failing.
- `references/render.md` — before touching a Render service: credentials, the CI path,
  and the remote-build fallback for when local Docker is dead.
- `references/supabase.md` — before `supabase db push`, before a one-off data fix, and
  when a repo is not `--linked`.
- `scripts/render.sh` — invoke as `bash scripts/render.sh <cmd> <service>`; do not rely
  on the executable bit (copy/sync tools often drop it). Credentials arrive as
  environment variables, never argv.
- `services.json` — the registry `render.sh` reads as `$SKILL_DIR/services.json`; it has
  to stay at this directory's root. The checked-in file is a placeholder example —
  replace it with your own services.
- `assets/deploy.yml` — the production workflow template copied into a repo at bootstrap.
