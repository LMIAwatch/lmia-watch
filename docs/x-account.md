# X account for the daily post

The nightly workflow can post one message a day to X: the count of Job Bank
postings with an LMIA requested that the night's pass saw for the first time,
their positions, the provinces, the three employers with the most positions,
and a link to the last seven days on the search page. The code is in
`pipeline/lmia_pipeline/social.py`. It does nothing until the four X secrets
below exist.

Nobody can create the account for you. X's signup checks an email address, may
ask for a phone number and can show a CAPTCHA, and automated signup breaks X's
rules.

## What it costs (checked 2026-10-17)

1. X closed free API access to new developers on 2026-02-06. Only apps X
   classes as public utilities keep free access, by manual review aimed at
   government bodies. Posting needs prepaid credits.
2. X's pricing page lists $0.015 per post and $0.20 per post that contains a
   link. One post a day costs about $6.10 a month with the link and about
   $0.46 a month without it.
3. The post carries no link by default; the attached card image shows the
   site address instead. Setting the repository variable `X_POST_LINK` to
   `true` (step 4) adds the link at the higher rate.
4. Each post attaches a card image (1200 by 675, drawn by the pipeline from the
   day's figures) with alt text. X's rate card lists no price for the upload
   and $0.005 for the alt text, so the image adds at most a cent a day.
5. Buying credits needs a verified phone number on the developer account and a
   payment card. A prepaid card can buy credits; it does not earn X's one-time
   $20 credit for a first card.
6. Set a monthly spending limit in the console and leave auto-recharge off.
   When the credits run out, X refuses the post, the step logs it, and the
   site refresh carries on as usual. Topping up is a manual step.

7. Reading through the API is billed too, so the nightly audience roll-up
   (`docs/search-engines.md`, section 6) records the Bluesky follower count
   and leaves the X one out.

This is the one part of the project that is not free. Decide on it before
step 2.

## 1. Create the account

1. Use a browser profile that has never signed in to a personal account of any
   kind.
2. Make a new email address for this account and nothing else. A plus-alias of
   an existing address does not serve: X's password reset page can show a
   masked hint of the address (its first letters and its domain) to anyone who
   types the handle. A free mailbox under a neutral name is enough.
3. Go to `x.com/signup`. Name: `LMIA Watch`. Enter the new address and the
   code X sends to it.
4. If X asks for a phone number, use one you accept X keeping on file. It is
   not shown on the profile, but the reset page can show its last digits.
   The developer console needs a verified number before it sells credits, so
   you will need one by step 2 either way.
5. Pick a neutral handle, for example `lmiawatch`.
6. Profile:
   - Bio: `Automated account run by LMIA Watch. One post a day from public Job Bank records.`
   - Website: the site address.
   - Picture: `brand/x-profile-400.png`. Header image: `brand/x-header-1500x500.png`.
7. Settings and privacy, Privacy and safety, Discoverability and contacts:
   turn off finding the account by email address and by phone number.
8. Settings and privacy, Security and account access: turn on two-factor
   authentication with an authenticator app.

## 2. Developer account and app

1. Signed in as the new account, open `console.x.com` and accept the Developer
   Agreement and Policy.
2. When the console asks how you will use the API, enter:
   `Posts one factual summary a day of new Job Bank postings that carry an LMIA requested flag, from public Government of Canada data, with a link to the public register. One post a day through POST /2/tweets. No reading of other accounts, no replies, mentions, likes, follows or direct messages.`
3. Create an app. Name: `LMIA Watch daily post`. Use the same text for the
   description and use case.
4. In the app's user authentication settings:
   - App permissions: Read and write.
   - Type of app: Automated app or bot.
   - Callback URI and website: the site address.
5. Under Keys and tokens:
   - Generate the API Key and Secret.
   - Generate the Access Token and Secret for the account.
   - Check that the access token says Read and write. If it says Read only, it
     was made before step 4; regenerate it.
6. The console shows each value once. Paste each into its GitHub secret
   (step 4) straight away. Do not save them in a file in the repository.
7. Under Billing: add the card, buy a small amount of credits, and set a
   monthly spending limit (for example $10).

## 3. Turn on the Automated label (a decision for you)

X's Developer Guidelines say an automated account must show the "Automated"
label, say in its bio that it is automated and who runs it, and be linked to a
human-managed account. X's help page on the label says the link connects the
managing account "to let everyone know who's managing it", so the managing
account is shown publicly.

To turn it on: on the bot account, Settings, Your account, Automation, then
choose the managing account and sign in to it.

The options:

1. Your personal account as manager. This names the operator on the profile,
   and X may show it on posts too. Do not do this.
2. A second project account as manager, for example `LMIA Watch Ops`, made the
   same way as in step 1 and used by hand. X asks for a human-run account.
   Its pages (read 2026-10-17) do not require the manager to show a real name,
   and its authenticity policy says no account has to display its owner's real
   identity. X does not say whether it accepts a pseudonymous manager in
   practice.
3. The account as its own manager. The setting asks you to sign in to another
   account, and X's pages do not describe an account managing itself. Treat
   this as unavailable.
4. No label, with the bio disclosure from step 1. This does not meet the
   Developer Guidelines' "must". X's automation rules say accounts and apps
   that break them may face enforcement up to suspension. X does not publish
   how it enforces the label.

Option 2 keeps the operator out of public view and meets the rule as written.
Option 4 is simpler and carries the risk above.

## 4. GitHub secrets

On the project's GitHub account, open the repository, then Settings, Secrets
and variables, Actions.

1. On the Secrets tab, add four repository secrets:

   | Secret | Value from the console |
   |---|---|
   | `X_API_KEY` | API Key |
   | `X_API_SECRET` | API Key Secret |
   | `X_ACCESS_TOKEN` | Access Token |
   | `X_ACCESS_TOKEN_SECRET` | Access Token Secret |

2. On the Variables tab, add `X_POST_ENABLED` with the value `true`. Without
   it the step is skipped, whatever secrets exist, so the cost decision above
   is made by setting this variable and nothing else.
3. Optional, on the Variables tab: `X_POST_LINK` set to `true` puts the site
   link in the text (thirteen times the per-post rate).
4. The next scheduled run posts. There is no manual trigger, by design.

## 5. Check locally before the first night

From the project account's own machine, never a personal one:

```
cd pipeline
pip install -e .[dev]
python -m lmia_pipeline post-digest --db ../data/lmia.sqlite --dry-run
```

This prints the post, writes it to `data/out/social/<date>.txt` with the card
beside it as `<date>.png`, and sends nothing. It needs no credentials. Add
`--link` to see the version with the link, `--no-image` to skip the card. Leave real posting to the workflow: X records the network address of
every API call, and a call from a home connection would tie the account to it
in X's records.

## What the job does each night

1. After the deploy, it reads the postings first seen on the latest completed
   Job Bank pass that carry the LMIA requested flag.
2. It posts nothing when there are none, when the database is new (every
   posting would look new), when the pass saw more than 500 new postings (a
   rebuild, not a day), or when that pass was already posted. A re-run of the
   workflow cannot post twice.
3. When the text runs past 280 characters, it drops employers from the end of
   the list first, then the province line. X counts the link as 23 characters.
4. Positions come from the vacancies a posting page states. When some pages
   have not been read yet, the post says "at least"; when fewer than half have
   been read, the positions figure is left out.
5. The date is the Eastern-time day of the pass. When the previous pass was
   more than 36 hours earlier, the wording becomes "since <that date>".
6. The card adds "Last 7 days": postings whose flag was first seen in the
   last seven days, leaving out any rebuild pass in that window.
7. The text is in the step's log in the Actions run. A failed post (no
   credits, X refusing, network trouble) exits 1, so the step shows red in the
   run while the refresh carries on, and LAST_RUN.md records the outcome.

Example:

```
Newly flagged "LMIA requested" on Job Bank, 2026-10-17: 41 postings, at least 123 positions.
In AB, BC, MB, NB, NS, ON, QC, SK
Most positions:
Example Greenhouses Ltd, Leamington ON: 40
Sample Berry Farms Inc, Abbotsford BC: 20
Serres Exemple Inc, Mirabel QC: 18
```

Attached: the card for the day, with the headline count, positions, new
postings by province as bars, up to five employers by positions, the source
line and the site address.

X's search rules ask accounts not to send automated posts, so X may leave the
account's posts out of search results. The posts still reach followers and
the profile.

## Sources (read 2026-10-17)

- X API pricing: `docs.x.com/x-api/getting-started/pricing`
- First-card credit: `docs.x.com/x-api/getting-started/free-credits`
- Pay-per-use launch and the end of free access: `devcommunity.x.com/t/256476`
- Phone number for credits: `docs.x.com/developer-terms/ppu-agreement`
- Getting access and credentials: `docs.x.com/x-api/getting-started/getting-access`
- Automated accounts: `docs.x.com/developer-guidelines` and `docs.x.com/fundamentals/developer-apps`
- The Automated label: `help.x.com/en/using-x/automated-account-labels`
- Automation rules: `help.x.com/en/rules-and-policies/x-automation`
- Authenticity policy: `help.x.com/en/rules-and-policies/authenticity`
- Search rules: `help.x.com/en/rules-and-policies/x-search-policies`
