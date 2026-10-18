# Donation notices from Ko-fi

The support page's figures (support received, the quarterly ledger, the
reserve) update themselves from Ko-fi's webhook. Ko-fi has no API for reading
past payments; the webhook is its only developer surface, and it fires once
per payment. Nothing on the site asks Ko-fi for anything.

## What the site keeps

One row per payment in the `donations` table: the transaction id, the time,
the kind (Donation, Subscription, Shop Order, Commission), the gross amount
and currency, and whether it was a membership payment. The donor's name,
email address, message and public flag are in the notice and are discarded
before storage. A repeated notice for the same transaction is ignored.

## Setup (once)

1. On Ko-fi, open Settings, then Webhooks (under More, or the API section).
2. Webhook URL: `https://lmiawatch.ca/hooks/kofi`.
3. Copy the verification token shown on the same page. It is a secret; do not
   put it in the repository.
4. Add it to the Worker from `site/`, with `CLOUDFLARE_API_TOKEN` in the
   environment:

   ```
   npx wrangler secret put KOFI_VERIFICATION_TOKEN
   ```

   paste the token at the prompt. Until the secret exists the route answers
   503 and stores nothing.
5. If the `donations` table is new to the deployed database, apply the schema
   once (every statement is `IF NOT EXISTS`):

   ```
   npx wrangler d1 execute lmia-watch --remote --file=../pipeline/schema.sql
   ```

6. Use Ko-fi's "Send test" button on the webhook page. The test notice carries
   a made-up transaction id and amount; the support page will show it. Delete
   it afterwards:

   ```
   npx wrangler d1 execute lmia-watch --remote --command "DELETE FROM donations WHERE transaction_id = '<the test id>'"
   ```

## How the figures are computed

- Support received: payments in the last 30 days. Canadian dollars count as
  given, US dollars at the page's planning rate, other currencies at face
  value.
- Ledger: one row per quarter since the site's first month. Received is the
  quarter's payments; spent is the monthly cost for each month that has
  started; reserve is cumulative received minus cumulative spent, never shown
  below zero. A shortfall is paid by the person who runs the site.
- Reserve months: the reserve divided by the full monthly cost of every tier,
  rounded down.

Amounts are gross. Ko-fi takes no platform fee on donations; the card
processor's fee is shown separately on the page as an estimate.

## If the webhook misses a payment

Ko-fi retries a failed delivery for a while and then stops. The Ko-fi
dashboard exports a CSV of payments; a missed one can be added by hand:

```
npx wrangler d1 execute lmia-watch --remote --command "INSERT OR IGNORE INTO donations (transaction_id, received_at, kind, amount_cents, currency, recurring, first_payment, created_at) VALUES ('<id>', '<ISO time>', 'Donation', 500, 'CAD', 0, 0, '<ISO now>')"
```
