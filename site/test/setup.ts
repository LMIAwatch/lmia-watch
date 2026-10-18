import { env } from "cloudflare:test";
import { beforeAll } from "vitest";

// Split a SQL file into statements: drop comment lines, then cut on a
// semicolon that ends a line. Seed values never contain ";\n".
export function splitSql(sql: string): string[] {
  const noComments = sql
    .split("\n")
    .map((line) => line.replace(/--.*$/, ""))
    .join("\n");
  return noComments
    .split(/;\s*\n/)
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
}

export async function applySql(db: D1Database, sql: string): Promise<void> {
  const statements = splitSql(sql);
  for (let i = 0; i < statements.length; i += 20) {
    await db.batch(statements.slice(i, i + 20).map((s) => db.prepare(s)));
  }
}

beforeAll(async () => {
  const e = env as unknown as { DB: D1Database; SCHEMA_SQL: string; SEED_SQL: string };
  await applySql(e.DB, e.SCHEMA_SQL);
  await applySql(e.DB, e.SEED_SQL);
});
