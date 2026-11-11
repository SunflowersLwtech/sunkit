<!-- public rewrite; the original internal copy is not shipped -->

# Vercel GitHub Actions CI/CD

Use this to set up a repo for GitHub Actions driven Vercel deployments.

Core shape:
- GitHub org secrets: `VERCEL_TOKEN`, `VERCEL_ORG_ID` when the repo can access organization secrets.
- Repo fallback secrets: `VERCEL_TOKEN`, `VERCEL_ORG_ID` for private repos under GitHub Free.
- Repo secret: `VERCEL_PROJECT_ID`.
- Repo workflow: `.github/workflows/deploy.yml` (template: `../assets/deploy.yml`,
  i.e. this skill's `assets/deploy.yml`).
- Repo Vercel config: `vercel.json` with `git.deploymentEnabled=false` to prevent native Vercel Git auto-deploys.

Do not print, commit, or save secret values. Pipe secrets directly into `gh secret set`.

## Role Split

Daily developers only need:
- a GitHub account that belongs to the project's GitHub org;
- access to the target GitHub repository;
- normal Git workflow: branch, commit, PR or push to `main`.

They do not need:
- a personal Vercel account;
- a personal Vercel team seat;
- `VERCEL_TOKEN`, `VERCEL_ORG_ID`, or `VERCEL_PROJECT_ID`;
- `.vercel/project.json`;
- `vercel login`, `vercel link`, or manual Vercel dashboard access.

Only the bootstrap maintainer or deployment agent needs Vercel access. For a new repo, the maintainer links or creates the Vercel project once, writes the required GitHub secrets, commits the workflow/config files, and verifies one successful GitHub Actions deployment. After that, teammates deploy by GitHub only.

## Guardrails

- This is standard CI automation with one authorized Vercel deploy token. Do not promise that it bypasses any required Vercel billing or seat rules.
- Team members who need Vercel dashboard access should be managed according to Vercel plan permissions.
- Keep `.vercel/` ignored. It may exist locally for `orgId` and `projectId`, but it must not be committed.
- Prefer org-level `VERCEL_TOKEN` and `VERCEL_ORG_ID`; keep `VERCEL_PROJECT_ID` per repo.
- GitHub Free does not expose organization-level secrets or variables to private repositories. If Actions sees empty `VERCEL_TOKEN` or `VERCEL_ORG_ID`, mirror those two values as repo secrets.
- If the Vercel CLI is logged into the wrong account, stop and re-authenticate the account that owns or can deploy the target project.
- Create long-lived Vercel API tokens from the Vercel Dashboard Tokens page. A Vercel CLI OAuth login token cannot be used to create another long-lived token through the API.

## Daily Developer Workflow

Use this path when a teammate is already in the org and the repository has been bootstrapped:

```bash
git clone git@github.com:YOUR_GITHUB_ORG/<repo>.git
cd <repo>
npm ci
npm run lint
git checkout -b <feature-branch>
```

Then commit and push through GitHub. A push to `main` triggers production deployment through GitHub Actions. The teammate should check the GitHub Actions run, not the Vercel dashboard.

If a teammate asks for Vercel details during normal development, answer: "You do not need Vercel access for this repo. Deployment is handled by GitHub Actions using repository secrets."

## When Vercel Login Is Actually Needed

Ask a developer to log in to Vercel only when they are temporarily acting as the bootstrap maintainer for a repo. Normal feature work never requires Vercel login.

Vercel access is needed for these one-time or rare tasks:
- creating or linking the Vercel project for a new repo;
- reading `orgId` and `projectId` from `.vercel/project.json`;
- creating or rotating the deploy token (`GITHUB_ACTIONS_DEPLOY`);
- changing Vercel project settings, domains, framework settings, or production environment variables;
- diagnosing a deployment failure that GitHub Actions logs cannot explain.

If the assigned maintainer does not already have an active Vercel session, prompt them to log in with the account that owns the Vercel team. If they cannot complete that login, ask another teammate with access to run the bootstrap or provide a maintainer-run handoff containing the project name, team slug, `orgId`, `projectId`, and confirmation that the deploy token has been written to GitHub secrets.

Never ask the owner to paste `VERCEL_TOKEN` into chat. The owner or maintainer should write it directly into GitHub Actions secrets, or place it briefly in an ignored local `.env` and pipe it into `gh secret set`.

After the bootstrap checklist passes once for a repo, developers can deploy by pushing with their own GitHub accounts. The GitHub commit author stays as the developer, while Vercel sees the GitHub Actions deployment token.

## Bootstrap A New Repo

Use this path only for the maintainer or deployment agent with Vercel access.

1. Confirm GitHub access:

```bash
gh auth status -h github.com
gh auth refresh -h github.com -s admin:org
```

2. Link the Vercel project locally:

```bash
vercel login
vercel link --yes --project <vercel-project-name> --scope <team-or-account-slug>
```

3. Create or retrieve the Vercel deployment token:

- In Vercel Dashboard, open Account Settings -> Tokens.
- Create a token named `GITHUB_ACTIONS_DEPLOY`, scoped to the project's team when possible.
- Put the token in a local ignored `.env` as `VERCEL_TOKEN=...` only long enough to write GitHub secrets.

4. Read IDs without printing full values in chat:

```bash
node -e "const p=require('./.vercel/project.json'); console.log(p.orgId);"
node -e "const p=require('./.vercel/project.json'); console.log(p.projectId);"
```

5. Set GitHub secrets:

```bash
printf %s "$VERCEL_TOKEN" | gh secret set VERCEL_TOKEN --org YOUR_GITHUB_ORG --app actions --visibility all
node -e "process.stdout.write(require('./.vercel/project.json').orgId)" | gh secret set VERCEL_ORG_ID --org YOUR_GITHUB_ORG --app actions --visibility all
node -e "process.stdout.write(require('./.vercel/project.json').projectId)" | gh secret set VERCEL_PROJECT_ID --repo YOUR_GITHUB_ORG/<repo> --app actions
```

For private repos on GitHub Free, also set repo-level fallbacks:

```bash
printf %s "$VERCEL_TOKEN" | gh secret set VERCEL_TOKEN --repo YOUR_GITHUB_ORG/<repo> --app actions
node -e "process.stdout.write(require('./.vercel/project.json').orgId)" | gh secret set VERCEL_ORG_ID --repo YOUR_GITHUB_ORG/<repo> --app actions
```

6. Add workflow/config files. The workflow template ships with this skill —
   point `<skill_dir>` at the installed `skills/web-deploy` directory:

```bash
mkdir -p .github/workflows
cp <skill_dir>/assets/deploy.yml .github/workflows/deploy.yml
```

Create or update `vercel.json`:

```json
{
  "$schema": "https://openapi.vercel.sh/vercel.json",
  "git": {
    "deploymentEnabled": false
  }
}
```

7. Verify:

```bash
gh secret list --org YOUR_GITHUB_ORG --app actions
gh secret list --repo YOUR_GITHUB_ORG/<repo> --app actions
npm run lint
npm run build
git add .github/workflows/deploy.yml vercel.json
git commit -m "Add Vercel GitHub Actions deployment"
git push
gh run list --repo YOUR_GITHUB_ORG/<repo> --workflow deploy.yml --limit 5
```

If the run fails at `vercel pull` and the log shows empty `VERCEL_TOKEN` or `VERCEL_ORG_ID`, set repo-level fallback secrets and rerun the failed job.

## Workflow Notes

- Production deploys run only from `main` plus manual `workflow_dispatch`.
- The workflow builds with `vercel build --prod` and deploys with `vercel deploy --prebuilt --prod`.
- Keep preview deployments out by default. Add a separate preview workflow only when the repo needs PR preview URLs.
- If `vercel pull` fails in Actions, the usual causes are a wrong `VERCEL_TOKEN`, wrong `VERCEL_PROJECT_ID`, or a token that belongs to a Vercel account without access to the project.
