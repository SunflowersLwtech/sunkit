<!-- public rewrite; the original internal copy is not shipped -->

## Supabase

**Always look before pushing:**

```bash
supabase migration list --linked   # compare the local and remote columns
```

**A divergence is usually a bookkeeping lie, not a real one.** On one project it looked alarming — the remote carried two migrations the repo had never seen, and none of the repo's were recorded as applied — so `db push` was avoided for months on the theory it would replay the initial schema. It would not have: the two "extra" remote entries were byte-identical copies of the repo's first two under later timestamps (written at 10:30, executed at 12:27, recorded under the execution time). Before working around a divergence, diff the files and check whether the objects actually exist:

```bash
supabase db query "select table_name from information_schema.tables where table_schema='public'" --linked
```

If the schema is really there, the fix is the ledger, not the database:

```bash
supabase migration repair --status applied  <version> --linked   # it ran; record it
supabase migration repair --status reverted <version> --linked   # it did not; forget it
supabase migration fetch --linked                                # pull remote-only files into the repo
```

`repair` writes only to `supabase_migrations.schema_migrations` — no DDL is re-run, so it cannot damage data.

**One-off data fixes:** `supabase db query "<sql>" --linked` runs straight against the remote and accepts `returning`, so the change verifies itself in the same call. Use it instead of inventing a migration for a single `update`. Read the current state first, and count what references the rows you are about to touch:

```bash
supabase db query "select name, active from public.items order by sort_order" --linked
supabase db query "update public.items set active = false where name = 'X' returning name, active" --linked
```

**Repo not linked:** `--linked` fails with "Cannot find project ref" on any repo without a `supabase/` link. Do not `supabase link` from a product repo just to run one query — a link from the wrong cwd leaves `supabase/.temp` in whatever repo you were standing in. Run the SQL through the Management API instead. It reaches `auth.*` too, which PostgREST never exposes:

```bash
curl -s -X POST "https://api.supabase.com/v1/projects/<project-ref>/database/query" \
  -H "Authorization: Bearer $SUPABASE_MGMT_TOKEN" -H "Content-Type: application/json" \
  -d "$(jq -cn --arg q "select id, email, email_confirmed_at from auth.users order by created_at desc limit 10" '{query:$q}')"
```

Tokens: `SUPABASE_MGMT_TOKEN` is the Management API access token, created from the dashboard (Account → Access Tokens). The `sbp_` token the CLI keeps in the macOS keychain (`Supabase CLI` item) is a different token and answers `Your account does not have the necessary privileges to access this endpoint` even though `supabase projects list` works with it — switch tokens before suspecting the query. Applying a migration file this way works (`-d "$(jq -cn --arg q "$(cat db/migrations/X.sql)" '{query:$q}')"`) but writes nothing to `schema_migrations`; repair the ledger afterwards if the repo tracks one.

Keep project refs (the `<project-ref>` per service) in your own infra notes — this skill does not ship them.
