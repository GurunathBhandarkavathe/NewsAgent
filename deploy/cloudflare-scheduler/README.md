# Samachar Bharat External Scheduler

This Cloudflare Worker triggers the GitHub Actions publisher through
`workflow_dispatch` every 3 hours. It is used instead of GitHub's native
`schedule` event because GitHub Support confirmed scheduled workflows can be
delayed or dropped under load.

## Schedule

The Worker cron runs in UTC:

```text
30 0,3,6,9,12,15,18,21 * * *
```

This maps to these IST times:

```text
06:00, 09:00, 12:00, 15:00, 18:00, 21:00, 00:00, 03:00
```

## GitHub Token

Create a fine-grained GitHub personal access token:

- Repository access: `GurunathBhandarkavathe/NewsAgent`
- Repository permission: `Actions` = `Read and write`

Do not commit this token. Store it as a Cloudflare Worker secret:

```bash
cd deploy/cloudflare-scheduler
npx wrangler secret put GITHUB_TOKEN
```

## Deploy

```bash
cd deploy/cloudflare-scheduler
npx wrangler deploy
```

## Manual Test

After deployment, trigger the scheduled handler from local Wrangler:

```bash
npx wrangler dev
curl "http://localhost:8787/cdn-cgi/handler/scheduled?format=json"
```

Then check the GitHub workflow:

https://github.com/GurunathBhandarkavathe/NewsAgent/actions/workflows/publish-instagram.yml

You should see an event type of `workflow_dispatch`.
