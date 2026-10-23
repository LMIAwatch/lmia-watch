import type { Lang } from "./i18n";

export interface Env {
  DB: D1Database;
  // The hosted search database (wrangler.jsonc, binding SEARCH), filled by
  // the nightly sync. Optional: nothing reads it yet, and a page that does
  // must answer without it.
  SEARCH?: D1Database;
  DATA?: R2Bucket;
  ASSETS?: Fetcher;
  SCHEMA_SQL?: string;
  SEED_SQL?: string;
  // Support page: the payment page address and the button text in English
  // and French. Empty or unset DONATE_URL keeps donations closed (no button).
  DONATE_URL?: string;
  DONATE_LABEL?: string;
  DONATE_LABEL_FR?: string;
  // The donation page's webhook token (a Worker secret). Unset keeps the
  // webhook route closed; a notice is stored only when its token matches.
  KOFI_VERIFICATION_TOKEN?: string;
  // Rate limiters (wrangler.jsonc "ratelimits"). Absent in a bare test
  // environment, in which case nothing is limited.
  // Daily check: the email binding, the sender on the zone, and the operator's
  // address (a secret, never in the repository).
  ALERTS?: SendEmail;
  ALERT_FROM?: string;
  ALERT_EMAIL?: string;
  PAGE_LIMIT?: RateLimit;
  API_LIMIT?: RateLimit;
  DOWNLOAD_LIMIT?: RateLimit;
  FORM_LIMIT?: RateLimit;
  FEED_LIMIT?: RateLimit;
  // Aggregate response counts (src/views.ts). Absent in tests and local
  // development, in which case nothing is counted.
  VIEWS?: AnalyticsEngineDataset;
}

export type AppEnv = {
  Bindings: Env;
  Variables: { lang: Lang };
};
