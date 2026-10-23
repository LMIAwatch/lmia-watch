import { readFileSync } from "node:fs";
import { cloudflareTest } from "@cloudflare/vitest-pool-workers";
import { defineConfig } from "vitest/config";

// The schemas and seed are read here, on the Node side, and handed to the
// Workers runtime as plain text bindings; the setup file applies them to the
// local D1 databases (forms and search) before the tests run.
export default defineConfig({
  plugins: [
    cloudflareTest({
      wrangler: { configPath: "./wrangler.jsonc" },
      miniflare: {
        bindings: {
          SCHEMA_SQL: readFileSync("../pipeline/schema.sql", "utf8"),
          SEED_SQL: readFileSync("./seed/dev_seed.sql", "utf8"),
          SEARCH_SCHEMA_SQL: readFileSync("../pipeline/search_schema.sql", "utf8"),
        },
      },
    }),
  ],
  test: {
    include: ["test/**/*.test.ts"],
    setupFiles: ["./test/setup.ts"],
  },
});
