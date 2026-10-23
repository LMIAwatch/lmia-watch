// Bindings as the test runtime sees them. The pool's own type file refers to
// Cloudflare.Env, which wrangler normally generates; declaring it here keeps
// the typecheck self-contained.
declare namespace Cloudflare {
  interface Env {
    DB: D1Database;
    SEARCH: D1Database;
    DATA: R2Bucket;
    ASSETS: Fetcher;
    SCHEMA_SQL: string;
    SEED_SQL: string;
    DONATE_URL: string;
    DONATE_LABEL: string;
    DONATE_LABEL_FR: string;
  }
}

// Vite's ?raw suffix imports a file's text; the i18n test reads the client
// scripts this way to check the keys they ask for.
declare module "*?raw" {
  const content: string;
  export default content;
}
