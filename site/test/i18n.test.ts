import { describe, expect, it } from "vitest";
import mapJs from "../public/map.js?raw";
import searchJs from "../public/search.js?raw";
import { app } from "../src/index";
import {
  SAME_IN_BOTH, allKeys, basisText, fmtInt, fmtWage, frTypography, periodLabel, provinceName, rawEntry, streamLabel, t,
  type Key,
} from "../src/i18n";
import { MAP_CLIENT_KEYS } from "../src/pages/map";
import { SEARCH_CLIENT_KEYS } from "../src/pages/search";
import { emptyAssets, testEnv } from "./assets";

const EM_DASH = String.fromCharCode(0x2014);
const nbsp = (s: string) => s.replace(/[  ]/g, " ");

const get = (path: string, headers: Record<string, string> = {}, env: object = testEnv()) => app.request(path, { headers }, env);
const post = (path: string, fields: Record<string, string>, headers: Record<string, string> = {}) =>
  app.request(
    path,
    {
      method: "POST",
      headers: { "content-type": "application/x-www-form-urlencoded", ...headers },
      body: new URLSearchParams(fields).toString(),
    },
    testEnv(),
  );

// English sentences that must never reach a French page. Each one appears on
// an English page (checked below), so the list cannot go stale silently.
const SENTINELS = [
  "Support the Site",
  "What the Site Holds Today",
  "Known false positives",
  "Loading records",
  "Download these results",
  "Data Not Published Yet",
  "Page Not Found",
  "Submit an Employer Response",
  "Request a Correction",
  "Status Lifecycle",
  "Right of Reply",
  "Who Is Applying",
  "Pending now",
  "see posting",
  "Indicator Definitions",
  "Not yet funded",
  "Card processing fee",
  "Click a cluster",
  "Your name and role",
];

const FRENCH_PAGES = [
  "/?lang=fr",
  "/search?lang=fr",
  "/search?lang=fr&status=refused&province=NL",
  "/search?lang=fr&page=2",
  "/map?lang=fr",
  "/methodology?lang=fr",
  "/data?lang=fr",
  "/support?lang=fr",
  "/employers/emp-a000000001?lang=fr",
  "/employers/emp-a000000005?lang=fr",
  "/employers/emp-a000000008?lang=fr",
  "/employers/emp-ffffffffff?lang=fr",
  "/employers/emp-a000000001/respond?lang=fr",
  "/corrections?lang=fr",
  "/nothing-here?lang=fr",
  "/downloads/employers.csv?lang=fr",
];

// The data blocks hold {name} templates on purpose, and the JSON-LD search
// action holds {search_term_string}; the API table shows
// endpoint patterns with braces. Everything else must be filled in.
function visible(html: string): string {
  return html
    .replace(/<script type="application\/(?:ld\+)?json"[^>]*>[\s\S]*?<\/script>/g, "")
    .replace(/\{(id|fsa|PROV|YEAR)\}/g, "");
}

describe("dictionary", () => {
  it("has a French string for every key, different from the English unless listed", () => {
    const keys = allKeys();
    expect(keys.length).toBeGreaterThan(400);
    for (const key of keys) {
      const { en, fr } = rawEntry(key);
      expect(en.trim(), key).not.toBe("");
      expect(fr.trim(), key).not.toBe("");
      if (SAME_IN_BOTH.has(key)) expect(fr, key).toBe(en);
      else expect(fr, `${key} has no French yet`).not.toBe(en);
    }
  });

  it("has no em-dash in either language", () => {
    for (const key of allKeys()) {
      const { en, fr } = rawEntry(key);
      expect(en, key).not.toContain(EM_DASH);
      expect(fr, key).not.toContain(EM_DASH);
    }
  });

  it("keeps the same placeholders in both languages", () => {
    const names = (s: string) => [...s.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();
    for (const key of allKeys()) {
      const { en, fr } = rawEntry(key);
      expect(names(fr), key).toEqual(names(en));
    }
  });

  it("follows Canadian French punctuation", () => {
    for (const key of allKeys()) {
      const { fr } = rawEntry(key);
      expect(fr, `${key}: no space before ; ! ?`).not.toMatch(/\s[;!?]/);
      expect(fr, `${key}: a space before every colon`).not.toMatch(/[^ ]:/);
      expect(fr, `${key}: guillemets, not straight quotes`).not.toContain('"');
      expect(fr, `${key}: a space inside guillemets`).not.toMatch(/«(?! )|(?<! )»/);
    }
    expect(frTypography("Sources : « EIMT » d'EDSC, 5 $ US")).toBe("Sources : « EIMT » d’EDSC, 5 $ US");
  });

  it("fills placeholders and leaves English as written", () => {
    expect(t("en", "search.showing", { from: 1, to: 25, total: "5,883" })).toBe("Showing 1 to 25 of 5,883");
    expect(t("fr", "search.showing", { from: 1, to: 25, total: "5 883" })).toBe("Affichage de 1 à 25 sur 5 883");
    expect(t("en", "home.how_pending")).toContain("Job Bank's own");
  });
});

describe("formats", () => {
  it("groups numbers the way each language does", () => {
    expect(fmtInt(5883, "en")).toBe("5,883");
    expect(nbsp(fmtInt(5883, "fr"))).toBe("5 883");
    expect(nbsp(fmtInt(166497, "fr"))).toBe("166 497");
  });

  it("writes quarters as T1 2026 in French", () => {
    expect(periodLabel("2026Q1", "en")).toBe("2026 Q1");
    expect(periodLabel("2026Q1", "fr")).toBe("T1 2026");
    expect(periodLabel("2017Q1-Q2", "en")).toBe("2017 Q1 to Q2");
    expect(periodLabel("2017Q1-Q2", "fr")).toBe("T1 à T2 2017");
    expect(periodLabel("2015", "fr")).toBe("2015");
  });

  it("writes wages with a decimal comma and the dollar sign after", () => {
    expect(fmtWage(38, 40, "HOUR", "en")).toBe("$38.00 to 40.00/h");
    expect(nbsp(fmtWage(38, 40, "HOUR", "fr"))).toBe("38,00 à 40,00 $/h");
    expect(nbsp(fmtWage(52000, 52000, "YEAR", "fr"))).toBe("52000,00 $/an");
    expect(fmtWage(20, 20, "WEEK", "en")).toBe("$20.00 week");
    expect(nbsp(fmtWage(20, 20, "WEEK", "fr"))).toBe("20,00 $/semaine");
    expect(fmtWage(null, null, null, "fr")).toBe("s.o.");
  });

  it("names provinces and streams in French", () => {
    expect(provinceName("fr", "BC")).toBe("Colombie-Britannique");
    expect(provinceName("fr", "PE")).toBe("Île-du-Prince-Édouard");
    expect(provinceName("fr", "NL")).toBe("Terre-Neuve-et-Labrador");
    expect(provinceName("fr", "QC")).toBe("Québec");
    expect(provinceName("en", "QC")).toBe("Quebec");
    expect(streamLabel("fr", "Primary Agriculture")).toBe("Agriculture primaire");
    expect(streamLabel("fr", "Unknown Stream")).toBe("Unknown Stream");
  });
});

describe("indicator basis sentences", () => {
  it("translates every sentence form the pipeline writes", () => {
    const cases: [string, string][] = [
      ["Prevailing wage table not yet loaded.", "Table des salaires courants pas encore chargée."],
      ["Regional unemployment table not yet loaded.", "Table du chômage régional pas encore chargée."],
      ["No low-wage stream records.", "Aucun dossier dans le volet des postes à bas salaire."],
      ["No registry match yet.", "Aucune correspondance au registre pour l’instant."],
      ["No pending posting or list record to compare against.", "Aucune offre en attente ni inscription de liste à comparer."],
      ["Registered 2026-06-22, first record 2026-10-08 (108 days).", "Date d’enregistrement : 2026-06-22; premier dossier : 2026-10-08 (108 jours)."],
      ["Registered 2026-11-01, after the first record (2026-10-08).", "Date d’enregistrement : 2026-11-01, après le premier dossier (2026-10-08)."],
      ["Registered 2018-04-01, 3112 days before the first record.", "Date d’enregistrement : 2018-04-01, 3 112 jours avant le premier dossier."],
      ["No positive-list rows.", "Aucune inscription sur la liste positive."],
      [
        "NOC 85101: positive list in 4 consecutive quarters (2025Q2 to 2026Q1).",
        "CNP 85101 : liste positive pendant 4 trimestres consécutifs (T2 2025 à T1 2026).",
      ],
      ["Longest run of consecutive quarters for one occupation: 2.", "Plus longue série de trimestres consécutifs pour une profession : 2."],
      ["760 positions approved in 2026Q1.", "760 postes approuvés, T1 2026."],
      ["120 positions in 2026Q1, against a median quarter of 11.5.", "120 postes, T1 2026, pour un trimestre médian de 11,5."],
      ["Largest quarter: 12 positions (2025Q3).", "Trimestre le plus élevé : 12 postes (T3 2025)."],
      ["No negative-list rows.", "Aucune inscription sur la liste négative."],
      [
        "Refused in 2026Q1 (list published 2026-07-21); new posting observed 2026-08-02.",
        "Refus, T1 2026 (liste publiée le 2026-07-21); nouvelle offre observée le 2026-08-02.",
      ],
      [
        "2 refusal record(s), no new posting within 90 days of publication.",
        "2 dossier(s) de refus, aucune nouvelle offre dans les 90 jours suivant la publication.",
      ],
    ];
    for (const [en, fr] of cases) {
      const out = basisText("fr", en);
      expect(out.translated, en).toBe(true);
      expect(nbsp(out.text)).toBe(nbsp(fr));
      expect(basisText("en", en).text).toBe(en);
    }
    const basisKeys = allKeys().filter((k) => k.startsWith("basis."));
    expect(cases.length).toBe(basisKeys.length);
  });

  it("leaves a sentence it does not know in English, flagged", () => {
    expect(basisText("fr", "Something new from the pipeline.")).toEqual({ text: "Something new from the pipeline.", translated: false });
  });
});

describe("client scripts", () => {
  // Literal keys only; a prefix such as "status." + r.status is checked below.
  const literalKeys = (src: string) => [...src.matchAll(/\btx\("([^"]+)"/g)].map((m) => m[1]).filter((k) => !k.endsWith("."));
  const sentenceLiterals = (src: string) =>
    [...src.matchAll(/"((?:[^"\\]|\\.)*)"/g)].map((m) => m[1]).filter((s) => /\b[A-Z][a-z]+(?: [a-z]+)+/.test(s));

  it("ask only for strings their page supplies", () => {
    const search = new Set<string>(SEARCH_CLIENT_KEYS);
    for (const key of literalKeys(searchJs)) expect(search.has(key), `search.js uses ${key}`).toBe(true);
    for (const key of allKeys().filter((k) => /^(ind\.|wage\.unit\.)/.test(k))) expect(search.has(key), key).toBe(true);
    for (const s of ["pending", "approved", "refused", "lapsed"]) expect(search.has(`status.${s}`)).toBe(true);
    const map = new Set<string>(MAP_CLIENT_KEYS);
    for (const key of literalKeys(mapJs)) expect(map.has(key), `map.js uses ${key}`).toBe(true);
    for (const s of ["pending", "approved", "refused", "lapsed"]) expect(map.has(`status.${s}`)).toBe(true);
  });

  it("hold no English sentences of their own", () => {
    expect(sentenceLiterals(searchJs)).toEqual([]);
    expect(sentenceLiterals(mapJs)).toEqual([]);
    expect(searchJs).not.toContain('"en-CA")');
  });

  it("get their strings from a JSON block, with no inline executable script", async () => {
    for (const path of ["/search?lang=fr", "/map?lang=fr"]) {
      const html = await (await get(path)).text();
      for (const tag of html.match(/<script\b[^>]*>/g) ?? []) {
        expect(/\bsrc="|type="application\/json"/.test(tag), tag).toBe(true);
      }
      const block = html.match(/<script type="application\/json" id="i18n">([\s\S]*?)<\/script>/)?.[1] ?? "";
      expect(block).not.toMatch(/[<>&]/);
      const data = JSON.parse(block) as { lang: string; locale: string; strings: Record<string, string> };
      expect(data.lang).toBe("fr");
      expect(data.locale).toBe("fr-CA");
      const keys = path.startsWith("/search") ? SEARCH_CLIENT_KEYS : MAP_CLIENT_KEYS;
      expect(Object.keys(data.strings)).toEqual([...keys]);
      for (const key of keys) expect(data.strings[key]).toBe(t("fr", key as Key));
    }
    const search = JSON.parse(
      (await (await get("/search?lang=fr")).text()).match(/<script type="application\/json" id="i18n">([\s\S]*?)<\/script>/)?.[1] ?? "{}",
    );
    expect(search.strings["search.no_match"]).toBe("Aucun dossier ne correspond à ces filtres.");
    expect(nbsp(search.strings["search.gate_csv"])).toBe("Page des téléchargements (CSV)");
  });
});

describe("rendered French pages", () => {
  it("carry no leftover English, no unfilled placeholder and no em-dash", async () => {
    for (const path of FRENCH_PAGES) {
      const res = await get(path);
      const html = await res.text();
      expect(html, path).toContain('<html lang="fr">');
      for (const s of SENTINELS) expect(html, `${path} still says "${s}"`).not.toContain(s);
      expect(visible(html), `${path} has an unfilled placeholder`).not.toMatch(/\{\w+\}/);
      expect(html, path).not.toContain(EM_DASH);
    }
  });

  it("say the expected French on the main pages", async () => {
    const home = nbsp(await (await get("/?lang=fr")).text());
    expect(home).toContain("Qui demande à embaucher des travailleurs étrangers temporaires");
    expect(home).toContain("5 883");
    expect(home).toContain("T1 2026");
    expect(home).toContain("« EIMT demandée »");

    const search = nbsp(await (await get("/search?lang=fr")).text());
    expect(search).toContain("5 dossiers");
    expect(search).toContain("Colombie-Britannique");
    expect(search).toContain("Guichet-Emplois 50456228");
    expect(search).toContain("38,00 à 40,00 $/h");
    expect(search).toContain("Télécharger ces résultats (CSV)");
    expect(search).toContain("Page 1 sur 1");

    const loading = await (await get("/search?lang=fr&status=refused")).text();
    expect(loading).toContain("Chargement des dossiers");

    const meth = nbsp(await (await get("/methodology?lang=fr")).text());
    expect(meth).toContain('<h2 id="status">Cycle de vie des statuts</h2>');
    expect(meth).toContain("Faux positifs connus");

    const support = nbsp(await (await get("/support?lang=fr")).text());
    expect(support).toContain("<h1>Soutenir le site</h1>");
    expect(support).toContain("Ce que le site contient aujourd’hui");
    expect(support).toContain("Toutes les listes trimestrielles d’EDSC depuis 2014 sont chargées, jusqu’au T1 2026.");
    expect(support).toContain("(166 497 employeurs)");
    expect(support).toContain("Frais de traitement par carte : 0,59 $ (2,9 % plus 30 cents)");
    expect(support).toContain("Réserve détenue : 0 sur 12 mois.");
    expect(support).toContain('<td class="tier-status">Pas encore financé</td>');
    expect(support).toContain(">Soutenir sur Ko-fi</a>");

    const employer = nbsp(await (await get("/employers/emp-a000000001?lang=fr")).text());
    expect(employer).toContain("Date d’enregistrement : 2026-06-22; premier dossier : 2026-10-08 (108 jours).");
    expect(employer).toContain("Déclenché");
    expect(employer).toContain("CNP 60040");
    expect(employer).toContain("1 publiée");
  });

  it("show the 503 page and form errors in French", async () => {
    const empty = await get("/?lang=fr", {}, testEnv(emptyAssets));
    expect(empty.status).toBe(503);
    expect(await empty.text()).toContain("Données pas encore publiées");

    const bad = await post("/employers/emp-a000000001/respond", { name: "O", email: "nope", statement: "short" }, { cookie: "lang=fr" });
    expect(bad.status).toBe(400);
    const html = await bad.text();
    expect(html).toContain("Inscrivez une adresse de courriel professionnelle valide.");
    expect(html).toContain("La déclaration doit compter au moins 20 caractères.");
    expect(html).not.toContain("valid work email");

    const ok = await post("/corrections", { record_ref: "Job Bank 1", request: "Wage is shown with the wrong unit." }, { cookie: "lang=fr" });
    expect(await ok.text()).toContain("Votre demande de correction a été reçue.");
  });

  it("keep the sentinel list honest: each phrase is on an English page", async () => {
    const pages = await Promise.all(
      ["/", "/search", "/search?status=refused", "/map", "/methodology", "/data", "/support", "/employers/emp-a000000001", "/nothing-here", "/employers/emp-a000000001/respond"].map(
        async (p) => (await get(p)).text(),
      ),
    );
    pages.push(await (await get("/", {}, testEnv(emptyAssets))).text());
    const all = pages.join("\n");
    for (const s of SENTINELS) expect(all, s).toContain(s);
  });
});
