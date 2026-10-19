import { describe, expect, it } from "vitest";
import { validCitation } from "../src/cite";
import { app } from "../src/index";
import { fakeAssets, testEnv } from "./assets";
import stats from "./fixtures/stats.json";

const EM_DASH = String.fromCharCode(0x2014);
const CITATION = {
  title: "LMIA Watch: ESDC positive and negative LMIA employer lists, derived files",
  concept_doi: "10.5281/zenodo.1000001",
  doi: "10.5281/zenodo.1000005",
  version: "2026Q1",
  published: "2026-10-19",
};

// The fixture export with a citation added, served the way the assets binding serves the real one.
function withCitation(citation: unknown): Fetcher {
  return {
    fetch: async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (new URL(url).pathname === "/data/stats.json") {
        return new Response(JSON.stringify({ ...stats, citation }), { headers: { "content-type": "application/json" } });
      }
      return fakeAssets.fetch(input as RequestInfo, init);
    },
  } as unknown as Fetcher;
}

const get = async (path: string, assets: Fetcher) => (await app.request(path, {}, testEnv(assets))).text();

describe("how to cite", () => {
  it("stays hidden until a DOI exists", async () => {
    for (const path of ["/data", "/methodology", "/data?lang=fr"]) {
      expect(await get(path, fakeAssets), path).not.toContain('id="cite"');
      expect(await get(path, withCitation(null)), path).not.toContain('id="cite"');
    }
    expect(await get("/data", withCitation({ ...CITATION, concept_doi: "javascript:alert(1)" }))).not.toContain('id="cite"');
  });

  it("shows the version DOI and the concept DOI on the Data and Methodology pages", async () => {
    for (const path of ["/data", "/methodology"]) {
      const html = await get(path, withCitation(CITATION));
      expect(html, path).toContain('<h2 id="cite">How to Cite</h2>');
      expect(html).toContain("LMIA Watch (2026). <cite>LMIA Watch: ESDC positive and negative LMIA employer lists, derived files</cite> (Version 2026Q1) [Data set]. Zenodo.");
      expect(html).toContain('<a href="https://doi.org/10.5281/zenodo.1000005">https://doi.org/10.5281/zenodo.1000005</a>');
      expect(html).toContain('<a href="https://doi.org/10.5281/zenodo.1000001">https://doi.org/10.5281/zenodo.1000001</a>');
      expect(html).not.toContain(EM_DASH);
    }
  });

  it("speaks French on French pages", async () => {
    const html = (await get("/data?lang=fr", withCitation(CITATION))).replace(/[  ]/g, " ");
    expect(html).toContain('<h2 id="cite">Comment citer</h2>');
    expect(html).toContain("(version 2026Q1) [Jeu de données]. Zenodo.");
    expect(html).toContain("utilisez le DOI de concept");
    expect(html).not.toContain("How to Cite");
    expect(html).not.toContain("[Data set]");
  });

  it("falls back to the concept DOI alone when the version DOI is missing", async () => {
    const html = await get("/data", withCitation({ ...CITATION, doi: null }));
    expect(html).toContain('<a href="https://doi.org/10.5281/zenodo.1000001">');
    expect(html).not.toContain("concept DOI");
  });

  it("accepts only DOI-shaped values", () => {
    expect(validCitation(CITATION)).toEqual(CITATION);
    expect(validCitation(null)).toBeNull();
    expect(validCitation(undefined)).toBeNull();
    expect(validCitation({ ...CITATION, concept_doi: "https://doi.org/10.5281/zenodo.1" })).toBeNull();
    expect(validCitation({ ...CITATION, concept_doi: '10.5281/zenodo.1"><script>' })).toBeNull();
  });
});

describe("statements on the Data and Support pages", () => {
  it("says the site counts pages in aggregate, in both languages", async () => {
    const en = await get("/data", fakeAssets);
    expect(en).toContain("The site counts the pages it serves in aggregate");
    expect(en).toContain("keeps no IP address or other personal data");
    const fr = (await get("/data?lang=fr", fakeAssets)).replace(/[  ]/g, " ");
    expect(fr).toContain("Le site compte de façon agrégée les pages qu’il sert");
  });

  it("notes that the Bluesky post is free", async () => {
    expect(await get("/support", fakeAssets)).toContain("The same daily post on Bluesky is free to send");
    expect(await get("/support?lang=fr", fakeAssets)).toContain("La même publication quotidienne sur Bluesky est gratuite");
  });
});
