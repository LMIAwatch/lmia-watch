# Bluesky account for the daily post

The nightly workflow posts the same daily digest to Bluesky as to X: the
postings that the night's Job Bank pass saw for the first time with an LMIA
requested, their positions, the provinces, the employers with the most
positions, and the card image with its alt text. Posting to Bluesky is free,
so this post also carries the link to the last seven days on the search
page. The code is in `pipeline/lmia_pipeline/bluesky.py`; it reuses the X
post's composition and card from `social.py`.

State on 2026-10-18: the account exists as `lmiawatch.ca`, and the
repository holds the secrets `BSKY_HANDLE` and `BSKY_APP_PASSWORD` and the
variable `BSKY_POST_ENABLED=true`. The steps below record how it was set up,
for a rebuild or a second operator.

## 1. Create the account

1. Use the project's browser profile, never signed in to a personal account
   of any kind.
2. Go to `bsky.app` and choose Create account, hosting provider Bluesky
   Social.
3. Email: the project's plus-alias address. Bluesky shows the address on no
   public page. Before relying on the alias, check that the password reset
   form asks for the address rather than showing a hint of it for a handle;
   if it ever shows a hint, use a separate mailbox, as for X.
4. Date of birth: Bluesky asks for one at sign-up; it is not shown on the
   profile.
5. Handle: `lmiawatch` (the account becomes `lmiawatch.ca`).
6. Profile:
   - Display name: `LMIA Watch`.
   - Description: `Automated account run by LMIA Watch. One post a day from public Job Bank records. lmiawatch.ca`
   - Avatar: `brand/x-profile-400.png`. Banner: `brand/x-header-1500x500.png`
     (Bluesky's banner is 3 to 1, the same shape).
7. Settings, Privacy and security: turn on two-factor sign-in by email. App
   passwords (step 4) are not affected by it.

## 2. Mark it as automated

Bluesky's guidance for bots asks an automated account to say so with a
self-label on its profile, and the app (version 1.119 and later) has a
setting for it that shows a label on the profile and on every post. Turn it
on in the account settings of the app (the switch that marks the account as
automated, or a bot). Unlike X's label, it needs no managing account, so
nothing names the operator.

Keep the description from step 1, which says the account is automated and
who runs it.

The job only ever creates posts. It never replies, likes, reposts, follows
or mentions anyone, which keeps to Bluesky's request that a bot interact
only with people who asked it to.

## 3. Custom handle lmiawatch.ca (optional)

The handle can be the site's own domain, which shows readers that the
account belongs to the site. Bluesky checks a DNS record for it.

1. In the app: Settings, Account, Handle, I have my own domain. Enter
   `lmiawatch.ca` and choose the DNS panel. Bluesky shows a TXT record: host
   `_atproto`, value `did=did:plc:` followed by the account's id.
2. Cloudflare dashboard, signed in as the project account: the
   `lmiawatch.ca` zone, DNS, Records, Add record. Type TXT, name `_atproto`,
   content the value Bluesky showed (`did=did:plc:...`, copied exactly), TTL
   Auto. Save. The workflow's API token cannot edit DNS, so this is a
   dashboard step.
3. Back in the app: Verify DNS Record, then Update to lmiawatch.ca.
4. Change the `BSKY_HANDLE` secret to `lmiawatch.ca`. With the old handle the
   sign-in fails, the post reports `failed`, and the daily check sends an
   alert.

The record holds only the account's id, which is public anyway. The posts
and followers stay with the account. Links that name the old handle
(`lmiawatch.ca`) stop working, and that handle becomes free for
anyone to take.

## 4. App password

Never give the workflow the account password. An app password can post but
cannot change the account's email or password or delete the account, and it
can be revoked on its own.

1. Settings, Privacy and security, App passwords, Add App Password.
2. Name: `nightly workflow`. Leave "Allow access to your direct messages"
   off.
3. Copy the password (four groups of four characters). It is shown once.
   Paste it straight into the GitHub secret (step 5) and do not save it in a
   file in the repository.

## 5. GitHub secrets and variable

On the project's GitHub account: the repository, Settings, Secrets and
variables, Actions.

| Tab | Name | Value |
|---|---|---|
| Secrets | `BSKY_HANDLE` | `lmiawatch.ca` (or `lmiawatch.ca` after step 3) |
| Secrets | `BSKY_APP_PASSWORD` | the app password from step 4 |
| Variables | `BSKY_POST_ENABLED` | `true` |

Without the variable the step is skipped; without either secret it logs
"The Bluesky secrets are not set" and posts nothing. The next scheduled run
posts. There is no manual trigger, by design.

## 6. Dry run

From the project account's own machine, never a personal one:

```
cd pipeline
pip install -e .[dev]
python -m lmia_pipeline post-bluesky --db ../data/lmia.sqlite --dry-run
```

This prints the post, writes it to `data/out/social/<date>.bluesky.txt` with
the card beside it as `<date>.png`, and sends nothing. It needs no
credentials. `--no-image` skips the card. Leave real posting to the
workflow, so the account's sign-ins come from GitHub's runners and not from
a home connection.

## What the job does each night

1. After the deploy and the X step, it reads the same digest as the X post.
2. It posts nothing when there are no new postings, when the database is new
   (every posting would look new), when the pass saw more than 500 new
   postings (a rebuild), or when that pass was already posted to Bluesky. The
   date of the pass posted is kept under its own key
   (`bsky_last_post_date`), so a re-run never posts twice, and the X and
   Bluesky posts do not depend on each other.
3. The text is the X text with the link on the last line. Bluesky allows 300
   characters (graphemes) and counts the link in full; when the text runs
   long, employers are dropped from the end first, then the province line.
   The link is made clickable with a link facet over its exact bytes; nothing
   else in the text becomes a link or a mention.
4. It signs in with the app password and reads the account's 25 newest
   posts (the public `listRecords` call, sent without the session token).
   When one of them has exactly tonight's text, the post went out on an
   earlier try whose answer was lost: the job records that post's address
   and date, reports `already posted` and sends nothing. When the listing
   cannot be read, it posts as usual.
5. It uploads the card (Bluesky allows up to 1,000,000 bytes; the card is
   about 75 KB) and creates the post with the card and its alt text. When
   the upload fails the text goes out alone.
6. A refused sign-in or post exits 1, so the step shows red while the
   refresh carries on. The outcome is recorded as `bluesky_post` in the run
   status, the workflow's last step lists it, the Worker's daily check emails
   the alert address, and LAST_RUN.md records it.

To stop posting, set `BSKY_POST_ENABLED` to `false`. To cut off access,
delete the app password in the account's settings.

Separately, the nightly audience roll-up (`docs/search-engines.md`, section
6) reads the account's follower count from the public profile endpoint
(`app.bsky.actor.getProfile` on `public.api.bsky.app`, no password or token)
and keeps it in `views/summary.csv` in R2. It uses the `BSKY_HANDLE` secret,
or the site's domain when that is not set, and does not depend on
`BSKY_POST_ENABLED`.

## Sources

- Posts, images and alt text through the AT Protocol (createSession,
  uploadBlob, createRecord): `docs.bsky.app/docs/advanced-guides/posts`
- Reading a repository's records (listRecords, no authentication):
  `docs.bsky.app/docs/api/com-atproto-repo-list-records`
- Link facets and their UTF-8 byte offsets: `docs.bsky.app/docs/advanced-guides/post-richtext`
- Bots and the self-label: `docs.bsky.app/docs/starter-templates/bots`
- Custom domain handles: `bsky.social/about/blog/4-28-2023-domain-handle-tutorial`
