import { describe, expect, it } from "vitest";
import { app } from "../src/index";
import { lmiaGap } from "../src/pages/employer";
import type { Profile } from "../src/data";
import { tn } from "../src/i18n";
import profiles from "./fixtures/profiles-a00.json";
import { testEnv } from "./assets";

const get = (path: string) => app.request(path, {}, testEnv());
const nbsp = (s: string) => s.replace(/[  ]/g, " ");
const EM_DASH = String.fromCharCode(0x2014);
const shard = profiles as unknown as Record<string, Profile>;

// emp-a000000009 has three positive rows, one with 3 LMIAs (30 positions) and
// two from files with no LMIA count (10 and 5 positions), and one refused row
// from a file with no LMIA count (4 positions).
describe("LMIA count notes on the employer page", () => {
  it("counts the rows without an LMIA count, list by list", () => {
    const rows = shard["emp-a000000009"].esdc;
    expect(lmiaGap(rows)).toBe(2);
    expect(lmiaGap(rows, "positive")).toBe(2);
    expect(lmiaGap(rows, "negative")).toBe(1);
    expect(lmiaGap(shard["emp-a000000005"].esdc)).toBe(0);
    expect(lmiaGap(shard["emp-a000000008"].esdc, "negative")).toBe(0);
    const refused = { ...shard["emp-a000000008"].esdc[0], lmias: null };
    expect(lmiaGap([refused], "positive")).toBe(0);
    expect(lmiaGap([refused], "negative")).toBe(1);
  });

  it("counts a row without an LMIA count as one and shows the floor", async () => {
    const res = await get("/employers/emp-a000000009");
    expect(res.status).toBe(200);
    const html = await res.text();
    // 3 counted plus 2 rows without a count; 0 counted plus 1 row, so never a 0 beside positions.
    expect(html).toContain('<dd class="mono">at least 5 <span class="muted">(45 positions)</span></dd>');
    expect(html).toContain('<dd class="mono">at least 1 <span class="muted">(4 positions)</span></dd>');
    expect(html).not.toContain('<dd class="mono">0 <span class="muted">');
    expect(html).toContain(
      '<p class="muted small" id="lmia-count-note">The approved count includes 2 rows from files that carry no LMIA count, ' +
        "each counted as one LMIA, so the true count can be higher. The refused count includes 1 row from a file that carries " +
        "no LMIA count, counted as one LMIA, so the true count can be higher.</p>",
    );
    expect(html).not.toContain(EM_DASH);
  });

  it("says nothing when every row has a count", async () => {
    for (const id of ["emp-a000000005", "emp-a000000001", "emp-a000000008"]) {
      const html = await (await get(`/employers/${id}`)).text();
      expect(html, id).not.toContain("lmia-count-note");
      expect(html, id).not.toContain("at least");
    }
  });

  it("has singular and plural forms in both languages", async () => {
    const note = (lang: "en" | "fr", one: "employer.lmias_note_one" | "employer.refused_lmias_note_one", count: number) =>
      nbsp(tn(lang, one, one.replace("_one", "_many") as typeof one, count, { n: count }));
    expect(note("en", "employer.lmias_note_one", 1)).toBe(
      "The approved count includes 1 row from a file that carries no LMIA count, counted as one LMIA, so the true count can be higher.",
    );
    expect(note("en", "employer.refused_lmias_note_one", 3)).toBe(
      "The refused count includes 3 rows from files that carry no LMIA count, each counted as one LMIA, so the true count can be higher.",
    );
    expect(note("fr", "employer.lmias_note_one", 1)).toBe(
      "Le nombre d’EIMT approuvées compte comme une EIMT 1 inscription tirée d’un fichier qui n’indique aucun nombre d’EIMT; le nombre réel peut être plus élevé.",
    );

    const fr = nbsp(await (await get("/employers/emp-a000000009?lang=fr")).text());
    expect(fr).toContain('<dd class="mono">au moins 5 <span class="muted">(45 postes)</span></dd>');
    expect(fr).toContain(
      "Le nombre d’EIMT approuvées compte comme une EIMT chacune des 2 inscriptions tirées de fichiers qui n’indiquent aucun nombre d’EIMT; le nombre réel peut être plus élevé. " +
        "Le nombre d’EIMT refusées compte comme une EIMT 1 inscription tirée d’un fichier qui n’indique aucun nombre d’EIMT; le nombre réel peut être plus élevé.",
    );
    expect(fr).not.toContain("includes");
  });

  it("writes one position in the singular", async () => {
    // Haveli Restaurant Inc has 1 refused LMIA for 1 position.
    const html = await (await get("/employers/emp-a000000008")).text();
    expect(html).toContain('<dd class="mono">1 <span class="muted">(1 position)</span></dd>');
  });
});
