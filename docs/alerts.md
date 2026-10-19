# Alerts for maintenance items

The site tells its operator when it needs a hand, through two channels that
need no new account.

## 1. The Worker's daily check

Every day at 06:00 UTC (after the nightly run's window) a cron trigger runs
`site/src/watchdog.ts`. It reads what the nightly run leaves behind:

- `stats.json` (the data date on every page),
- the upload time of `lmia.sqlite.gz` in R2 (the backup),
- `status.json` in R2 (when the run finished, which stages succeeded, and
  the outcomes of the X post, the Bluesky post and the Zenodo deposit).

It emails when the data is more than two and a half days old, the backup or
the status is missing or older than 36 hours, a stage or a workflow step
(restore, deploy, save) failed, the checks held back the night's data, the
status file cannot be read, X or Bluesky refused the post, or the Zenodo
deposit failed. One email a day at most, repeated while an item remains. Nothing
is sent on a healthy day.

### One-time setup (dashboard, since the project token cannot do it)

1. Cloudflare dashboard, the lmiawatch.ca zone, Email, Email Routing, enable
   it (this adds the MX records the zone needs to send).
2. Destination addresses, Add, enter the operator's address, then click the
   verification link in the email Cloudflare sends.
3. From `site/`, with `CLOUDFLARE_API_TOKEN` in the environment:

   ```
   npx wrangler secret put ALERT_EMAIL
   ```

   and paste the same address. The sender is the `ALERT_FROM` variable
   (`alerts@lmiawatch.ca`), which needs no mailbox.

Until steps 1 and 2 are done, the check runs and logs, and sending fails
quietly.

## 2. GitHub's failed-workflow email

The nightly workflow's last step fails the run when a stage failed, the X or
Bluesky post was refused, or the Zenodo deposit failed, after everything else
has been saved and recorded. GitHub
then emails the account that owns the repository, provided its notification
settings keep "Actions: failed workflows" on (the default).

## What each item means

| Item | Likely cause | What to do |
|---|---|---|
| Data stale | The scheduled run has not completed for days | Open the Actions page; the log of the failed run says which stage |
| Backup missing or old | The R2 save step failed, or the run did not get that far | Same |
| Stage `jobbank` failed | Job Bank changed its pages or blocked the crawler | Check the run log; the page structure may need a parser update |
| Stage `esdc` failed | The open-data portal changed a file layout | Same |
| X post refused | Credits exhausted, keys revoked, or X down | X developer console: credits and app keys |
| Bluesky post refused | App password revoked, the handle changed without the `BSKY_HANDLE` secret, or Bluesky down | `docs/bluesky-account.md`: make a new app password, update the secrets |
| Zenodo deposit failed | Token revoked or expired, Zenodo down, or a field refused | The run log quotes Zenodo's answer; the next night tries again (`docs/zenodo.md`) |
