<!-- public rewrite; the original internal copy is not shipped -->

## Vercel: use the API, not the dashboard

**Keep the token out of argv and the terminal.** Have `VERCEL_TOKEN` in the shell
environment (export it, or source an ignored local `.env` that contains it), and
send the auth header on curl's stdin (`-H @-`) so no command line ever contains
it — the process table would show it plainly. Every project has
`.vercel/project.json` with the two ids the API needs (exported, so a `sh -c`
wrapper sees them):

```bash
export PID=$(python3 -c "import json;print(json.load(open('.vercel/project.json'))['projectId'])")
export TID=$(python3 -c "import json;print(json.load(open('.vercel/project.json'))['orgId'])")
```

`vercel whoami` may fail with *"Not authorized: … scope '<personal-team-slug>'"* —
that is your personal Hobby team, not the team that owns the project. Do not
conclude you are unauthenticated; the REST token works fine. Names, not
presence, are what `whoami` is bad at.

**List env vars**

```bash
sh -c 'printf "Authorization: Bearer %s\n" "$VERCEL_TOKEN" |
  curl -s -H @- "https://api.vercel.com/v10/projects/$PID/env?teamId=$TID"' \
| python3 -c "import json,sys;[print(e['key'],e['target']) for e in json.load(sys.stdin)['envs']]"
```

**Create one** — build the JSON body with `python3` reading the value from the environment, so the secret never lands in shell history or an argv the process table can see:

```bash
K="$(grep '^MY_VAR=' .env.local | cut -d= -f2-)" python3 -c "
import json,os
json.dump({'key':'MY_VAR','value':os.environ['K'],'type':'plain',
           'target':['production','preview','development'],
           'comment':'what this is and where it came from'}, open('/tmp/env.json','w'))"
sh -c 'printf "Authorization: Bearer %s\n" "$VERCEL_TOKEN" |
  curl -s -X POST -H @- -H "Content-Type: application/json" \
    --data @/tmp/env.json "https://api.vercel.com/v10/projects/$PID/env?teamId=$TID"'
rm -f /tmp/env.json
```

`type` is `plain` for values that are public by design (anything `NEXT_PUBLIC_*`) and `encrypted` for real secrets. Vercel's "Sensitive" toggle only controls read-back in the UI; it does not change what reaches the build.

**Check what actually deployed**

```bash
sh -c 'printf "Authorization: Bearer %s\n" "$VERCEL_TOKEN" |
  curl -s -H @- "https://api.vercel.com/v6/deployments?projectId=$PID&teamId=$TID&limit=3"' \
| python3 -c "import json,sys;[print(d['state'],d.get('target'),d['url']) for d in json.load(sys.stdin)['deployments']]"
```

### `NEXT_PUBLIC_*` needs a redeploy

Next inlines these at **build** time. Adding one to Vercel changes nothing on the live site until the next build. After creating one, trigger your normal redeploy path (`vercel deploy --prebuilt --prod`, or a no-change redeploy from the dashboard) and verify by checking the newest deployment's timestamp is after the env var's creation.

## Before you fix a stale-client bug

Next already ships version-skew protection and it is undocumented, so it is easy to "fix" twice over. Every `next build` mints a fresh nanoid build id, sends it in the RSC payload as `"b"`, and the router hard-navigates when the server answers with a different one. Check for it before building anything:

```bash
curl -s https://<host>/ | grep -oE '\\\\"b\\\\":\\\\"[A-Za-z0-9_-]+\\\\"'
```

Setting `deploymentId` in `next.config.ts` **replaces** that with a header the CDN has to deliver, freezes `BUILD_ID` to a constant, and puts `?dpl=` on every static asset so each deploy re-downloads them all — measured at ~313 KB per returning visitor per deploy on a real Next.js product, several deploys a day, to fix nothing.
