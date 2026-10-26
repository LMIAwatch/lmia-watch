import { describe, expect, it } from "vitest";
import mapJs from "../public/map.js?raw";
import searchJs from "../public/search.js?raw";
import { app } from "../src/index";
import {
  SAME_IN_BOTH, allKeys, basisText, fmtInt, fmtWage, frTypography, indicatorLabel, indicatorShortLabel, periodLabel, provinceName,
  rawEntry, streamLabel, t, type Key,
} from "../src/i18n";
import { INDICATORS } from "../src/constants";
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
  "Search is unavailable",
  "Download these results",
  "Data Not Published Yet",
  "Page Not Found",
  "Submit an Employer Response",
  "Request a Correction",
  "Status Lifecycle",
  "Right of Reply",
  "Who Is Applying",
  "now on Job Bank",
  "By Occupation",
  "Pending now",
  "see posting",
  "Indicator Definitions",
  "Not yet funded",
  "Card processing fee",
  "Click a cluster",
  "Your name and role",
  "is a secondary source",
  "Employer selected:",
  "touch these programs only in passing",
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
  "/employers/emp-a000000009?lang=fr",
  "/employers/emp-ffffffffff?lang=fr",
  "/employers/emp-a000000001/respond?lang=fr",
  "/corrections?lang=fr",
  "/nothing-here?lang=fr",
  "/downloads/employers.csv?lang=fr",
  "/program?lang=fr",
  "/international?lang=fr",
  "/notices?lang=fr",
  "/cite?lang=fr",
];

// The data blocks hold {name} templates on purpose, and the JSON-LD search
// action holds {search_term_string}; the API table shows
// endpoint patterns with braces, and a BibTeX entry on the citation page
// (a block that starts with @) braces its fields. Everything else must be
// filled in.
function visible(html: string): string {
  return html
    .replace(/<script type="application\/(?:ld\+)?json"[^>]*>[\s\S]*?<\/script>/g, "")
    .replace(/<pre class="cite-block">@[\s\S]*?<\/pre>/g, "")
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

  it("has a French unit for every unit the pipeline stores", () => {
    // normalize.parse_salary_text writes HOUR, YEAR, WEEK, MONTH, BIWEEK,
    // SEMIMONTH and DAY; the posting pages' schema.org unitText adds WEEKLY and
    // BIWEEKLY. Without a key, fmtWage would print the English code on a French row.
    for (const unit of ["HOUR", "YEAR", "WEEK", "MONTH", "BIWEEK", "SEMIMONTH", "DAY", "WEEKLY", "BIWEEKLY"]) {
      expect(allKeys(), unit).toContain(`wage.unit.${unit}`);
      expect(nbsp(fmtWage(20, 20, unit, "fr")), unit).not.toMatch(/[a-z]{4,}ly|week|month|hour/i);
    }
    expect(nbsp(fmtWage(700, 700, "WEEKLY", "fr"))).toBe("700,00 $/semaine");
    expect(nbsp(fmtWage(1500, 1500, "BIWEEKLY", "fr"))).toBe("1500,00 $/deux semaines");
    expect(nbsp(fmtWage(2000, 2000, "SEMIMONTH", "fr"))).toBe("2000,00 $/demi-mois");
    expect(fmtWage(1500, 1500, "BIWEEKLY", "en")).toBe("$1500.00 biweek");
  });

  it("shortens the long indicator labels for the search results, both languages", () => {
    expect(indicatorShortLabel("en", "low_wage_high_unemployment")).toBe("Low wage, high unemployment");
    expect(indicatorShortLabel("en", "wage_at_floor")).toBe("At the wage floor");
    expect(indicatorShortLabel("en", "newly_incorporated")).toBe("Newly incorporated");
    expect(indicatorShortLabel("en", "refused_then_reposted")).toBe("Refused, re-posted");
    expect(indicatorShortLabel("fr", "low_wage_high_unemployment")).toBe("Bas salaire, chômage élevé");
    expect(indicatorShortLabel("fr", "wage_at_floor")).toBe("Salaire au plancher");
    expect(indicatorShortLabel("fr", "newly_incorporated")).toBe("Constitué récemment");
    expect(indicatorShortLabel("fr", "refused_then_reposted")).toBe("Refus, nouvelle offre");
    for (const lang of ["en", "fr"] as const) {
      // Short already: the full label.
      for (const id of ["high_volume", "repeat_applicant"]) expect(indicatorShortLabel(lang, id)).toBe(indicatorLabel(lang, id));
      for (const id of INDICATORS) expect(indicatorShortLabel(lang, id).length).toBeLessThanOrEqual(indicatorLabel(lang, id).length);
    }
    expect(indicatorShortLabel("en", "something_new")).toBe("something_new");
    expect(t("en", "search.source_jobbank_short")).toBe("Job Bank");
    expect(t("fr", "search.source_jobbank_short")).toBe("Guichet-Emplois");
    expect(t("en", "search.source_esdc_short")).toBe("ESDC");
    expect(t("fr", "search.source_esdc_short")).toBe("EDSC");
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
      ["No Job Bank posting.", "Aucune offre du Guichet-Emplois."],
      [
        "No posting page parsed yet, so the occupation is unknown.",
        "Aucune page d’offre analysée pour l’instant : la profession est donc inconnue.",
      ],
      [
        "No posting has a postal code that places it in an economic region.",
        "Aucune offre n’a un code postal qui la situe dans une région économique.",
      ],
      ["No Job Bank median for NOC 99999.", "Aucune médiane du Guichet-Emplois pour la CNP 99999."],
      [
        "No posted wage matches the hourly or yearly unit of the Job Bank median.",
        "Aucun salaire affiché n’est dans l’unité horaire ou annuelle de la médiane du Guichet-Emplois.",
      ],
      [
        "Posting 101: posted minimum $17.10/h is within 1 percent of the Job Bank median $16.95/h for NOC 44101 in the Winnipeg economic region (Manitoba), wage table dated 2025-11-19.",
        "Offre 101 : salaire minimum affiché de 17,10 $/h, à 1 % ou moins de la médiane du Guichet-Emplois de 16,95 $/h pour la CNP 44101 (région économique Winnipeg, Manitoba), table des salaires du 2025-11-19.",
      ],
      [
        "Closest of 2 posting(s) compared: posting 102, posted minimum $99,000/yr against the Job Bank median $84,000/yr for NOC 00010 in Canada (national figure), wage table dated 2025-11-19.",
        "Offre la plus proche parmi 2 offre(s) comparée(s) : offre 102, salaire minimum affiché de 99 000 $/an pour une médiane du Guichet-Emplois de 84 000 $/an, CNP 00010 (Canada, chiffre national), table des salaires du 2025-11-19.",
      ],
      ["No low-wage approvals from 2025Q1 on.", "Aucune approbation dans le volet des postes à bas salaire depuis le T1 2025."],
      [
        "The low-wage approvals could not be placed in an area with a published unemployment rate.",
        "Les approbations dans le volet des postes à bas salaire n’ont pu être situées dans une région dont le taux de chômage est publié.",
      ],
      [
        "Low Wage stream approval in 2025Q4; the Winnipeg CMA unemployment rate was 6.4 percent for the three months ending 2025-06 and 6.6 percent for the three months ending 2025-09 (Statistics Canada LFS).",
        "Approbation dans le volet des postes à bas salaire, T4 2025; taux de chômage de 6,4 % pour les trois mois se terminant en 2025-06 et de 6,6 % pour les trois mois se terminant en 2025-09, région métropolitaine de recensement : Winnipeg (EPA de Statistique Canada).",
      ],
      [
        "1 low-wage positive-list row(s) from 2025Q1 on; none in a census metropolitan area at or above 6 percent in both three-month periods checked.",
        "1 inscription(s) sur la liste positive dans le volet des postes à bas salaire depuis le T1 2025; aucune dans une région métropolitaine de recensement à 6 % ou plus pendant les deux périodes de trois mois vérifiées.",
      ],
      // Rules 0.3: a quarter judged on ESDC's published refusal-to-process lists.
      [
        "Low Wage stream approval in 2026Q3; ESDC's refusal-to-process lists gave the Greater Sudbury CMA 6.4 percent from 2026-04-10 and 6.2 percent from 2026-07-10.",
        "Approbation dans le volet des postes à bas salaire, T3 2026; les listes de refus de traitement d’EDSC donnaient 6,4 % à compter du 2026-04-10 et 6,2 % à compter du 2026-07-10, région métropolitaine de recensement : Grand Sudbury.",
      ],
      [
        "2 low-wage positive-list row(s) from 2025Q1 on; none in a census metropolitan area at or above 6 percent in both periods checked: 1 against ESDC's published refusal-to-process lists, 1 against Statistics Canada LFS rates.",
        "2 inscription(s) sur la liste positive dans le volet des postes à bas salaire depuis le T1 2025; aucune dans une région métropolitaine de recensement à 6 % ou plus pendant les deux périodes vérifiées : 1 selon les listes de refus de traitement publiées par EDSC, 1 selon les taux de l’EPA de Statistique Canada.",
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

  it("names provinces, regions and metropolitan areas in French", () => {
    const fr = (en: string) => nbsp(basisText("fr", en).text);
    expect(
      fr("Posting 7: posted minimum $31.00/h is within 1 percent of the Job Bank median $31.00/h for NOC 22101 in British Columbia (provincial figure), wage table dated 2025-11-19."),
    ).toContain("CNP 22101 (Colombie-Britannique, chiffre provincial)");
    expect(
      fr("Closest of 1 posting(s) compared: posting 8, posted minimum $19.00/h against the Job Bank median $18.00/h for NOC 44101 in the Southeast economic region (Manitoba), wage table dated 2025-11-19."),
    ).toContain("(région économique Sud-est, Manitoba)");
    expect(
      fr("Closest of 1 posting(s) compared: posting 9, posted minimum $40.00/h against the Job Bank median $38.00/h for NOC 72106 in the Lower Mainland--Southwest economic region (British Columbia), wage table dated 2025-11-19."),
    ).toContain("(région économique Lower Mainland--Sud-ouest, Colombie-Britannique)");
    expect(
      fr("Low Wage stream approval in 2026Q1; the Greater Sudbury CMA unemployment rate was 6.2 percent for the three months ending 2025-09 and 6.0 percent for the three months ending 2025-12 (Statistics Canada LFS)."),
    ).toContain("région métropolitaine de recensement : Grand Sudbury");
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
    for (const key of allKeys().filter((k) => /^(ind\.|ind_short\.|wage\.unit\.)/.test(k))) expect(search.has(key), key).toBe(true);
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
    expect(nbsp(search.strings["search.total_capped"])).toBe("{n} ou plus");
    expect(search.strings["search.unavailable"]).toBe("La recherche est indisponible pour le moment, alors les dossiers les plus récents sont affichés.");
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
    // The two topic rows' heads and sub-heads.
    expect(home).toContain("</span> en ce moment au Guichet-Emplois <span class=\"topic-count\">5 883 offres portant la mention « EIMT demandée »</span>");
    expect(home).toContain("</span> au T1 2026 <span class=\"topic-count\">8 790 dossiers d’employeurs, 33 216 postes</span>");
    expect(home).toContain('<h3 class="sub">Par volet</h3>');

    const search = nbsp(await (await get("/search?lang=fr")).text());
    expect(search).toContain("5 dossiers");
    expect(search).toContain("Colombie-Britannique");
    expect(search).toContain('title="Guichet-Emplois 50456228">Guichet-Emplois</a>');
    expect(search).toContain("<th>Profession</th>");
    expect(search).toContain("38,00 à 40,00 $/h");
    expect(search).toContain("Télécharger ces résultats (CSV)");
    expect(search).toContain("Page 1 sur 1");

    // This file's search database is empty, so a filtered search falls back.
    const fallback = nbsp(await (await get("/search?lang=fr&status=refused")).text());
    expect(fallback).toContain('id="search-unavailable" role="status">La recherche est indisponible pour le moment, alors les dossiers les plus récents sont affichés.</p>');
    expect(fallback).toContain("Toutes les dates depuis 2014");

    const meth = nbsp(await (await get("/methodology?lang=fr")).text());
    expect(meth).toContain('<h2 id="status">Cycle de vie des statuts</h2>');
    expect(meth).toContain("Faux positifs connus");
    expect(meth).toContain("Enquête sur la population active de Statistique Canada, tableau 14-10-0459-01");
    expect(meth).toContain("la médiane provinciale, puis nationale");
    expect(meth).toContain("Depuis le 2024-09-26, EDSC refuse de traiter les demandes à bas salaire");
    expect(meth).not.toContain("(prévu)");

    const data = nbsp(await (await get("/data?lang=fr")).text());
    expect(data).toContain("Licence ouverte de Statistique Canada");
    expect(data).toContain("https://www150.statcan.gc.ca/t1/tbl1/fr/tv.action?pid=1410045901");
    expect(data).toContain('<td class="mono nw">2026-10-17</td>');
    expect(data).toContain("Ménages privés écartés des listes d’EDSC");
    expect(data).not.toContain("prévu");

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
      ["/", "/search", "/search?status=refused", "/map", "/methodology", "/data", "/support", "/cite", "/employers/emp-a000000001", "/nothing-here", "/employers/emp-a000000001/respond", "/international", "/notices"].map(
        async (p) => (await get(p)).text(),
      ),
    );
    pages.push(await (await get("/", {}, testEnv(emptyAssets))).text());
    const all = pages.join("\n");
    for (const s of SENTINELS) expect(all, s).toContain(s);
  });
});
