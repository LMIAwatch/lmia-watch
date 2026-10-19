import { describe, expect, it } from "vitest";
import watchlistJs from "../public/watchlist.js?raw";
import { app } from "../src/index";
import { t, type Key } from "../src/i18n";
import { FEED_EVENTS, nocGroupLabel } from "../src/pages/feeds";
import { WATCH_MAX, WATCHLIST_CLIENT_KEYS } from "../src/pages/watchlist";
import { DESCRIPTION_MAX } from "../src/seo";
import { fakeAssets, testEnv } from "./assets";
import feedIndex from "./fixtures/feeds-index.json";

const EM_DASH = String.fromCharCode(0x2014);
const nbsp = (s: string) => s.replace(/[  ]/g, " ");

// The shared fake assets plus the feed index, so the shared fixture list stays untouched.
function withFeeds(index: unknown): Fetcher {
  return {
    fetch: async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (new URL(url).pathname === "/data/feeds/index.json") {
        return typeof index === "string"
          ? new Response(index, { headers: { "content-type": "application/json" } })
          : new Response(JSON.stringify(index), { headers: { "content-type": "application/json" } });
      }
      return fakeAssets.fetch(input as Request, init);
    },
  } as unknown as Fetcher;
}

const get = (path: string, assets: Fetcher = withFeeds(feedIndex)) => app.request(path, {}, testEnv(assets));
const html = async (path: string, assets?: Fetcher) => (await get(path, assets)).text();

// English phrases from the two pages that must never reach their French versions.
const SENTINELS = [
  "Each feed lists the newest",
  "How to Subscribe",
  "What Each Feed Holds",
  "New pending postings",
  "Metropolitan area",
  "Addresses follow the pattern",
  "Press Watch on",
  "Since your last visit",
  "Move the List to Another Browser",
  "Show the code",
  "No employer is on the watchlist",
];

describe("feeds page", () => {
  it("lists the national feeds with their addresses and the scoped feeds from the index", async () => {
    const res = await get("/feeds");
    expect(res.status).toBe(200);
    const page = await res.text();
    expect(page).toContain("<h1>Atom Feeds</h1>");
    for (const e of FEED_EVENTS) {
      expect(page).toContain(`<a href="/data/feeds/canada/${e}.xml" class="mono" style="overflow-wrap:anywhere">https://lmiawatch.ca/data/feeds/canada/${e}.xml</a>`);
    }
    expect(page).toContain('href="/data/feeds/prov/BC/pending.xml" class="mono" aria-label="British Columbia: New pending postings">pending.xml</a>');
    expect(page).toContain('href="/data/feeds/stream/primary-agriculture/quarters.xml"');
    expect(page).toContain("73: trades, transport and equipment operators, TEER 3");
    expect(page).toContain("85: natural resources, agriculture and related production, TEER 5");
    expect(page).toContain(">Vancouver</td>");
    // A path outside feeds/ in the index is dropped, never linked.
    expect(page).not.toContain("secrets");
    // Head office outside Canada sorts after the provinces.
    expect(page.indexOf("British Columbia</td>")).toBeLessThan(page.indexOf("Newfoundland and Labrador</td>"));
    expect(page.indexOf("Newfoundland and Labrador</td>")).toBeLessThan(page.indexOf("Head office outside Canada</td>"));
    expect(page).toContain("/feed subscribe");
    expect(page).toContain("stores no reader address");
    expect(page).toContain('<a href="/watchlist">watchlist</a>');
    expect(page).toContain('<link rel="canonical" href="https://lmiawatch.ca/feeds"');
    expect(page).not.toContain(EM_DASH);
  });

  it("still lists the national feeds when the index is missing or unreadable", async () => {
    for (const assets of [fakeAssets, withFeeds("{not json"), withFeeds({ feeds: "nope" })]) {
      const res = await get("/feeds", assets);
      expect(res.status).toBe(200);
      const page = await res.text();
      expect(page).toContain("https://lmiawatch.ca/data/feeds/canada/pending.xml");
      expect(page).toContain("The province, stream, occupation and area feeds are listed after the next nightly update.");
    }
  });

  it("adds Atom autodiscovery for the national feeds to the home, search and feeds pages", async () => {
    for (const path of ["/", "/search", "/feeds"]) {
      const page = await html(path);
      for (const e of FEED_EVENTS) {
        expect(page, `${path} ${e}`).toMatch(new RegExp(`<link rel="alternate" type="application/atom\\+xml" title="LMIA Watch: [^"]+, Canada" href="/data/feeds/canada/${e}.xml"`));
      }
    }
    const fr = nbsp(await html("/?lang=fr"));
    expect(fr).toContain('title="LMIA Watch : Nouvelles offres en attente, Canada" href="/data/feeds/canada/pending.xml"');
  });

  it("names occupation groups by category and TEER in both languages", () => {
    expect(nocGroupLabel("en", "00")).toBe("00: legislative and senior management occupations, TEER 0");
    expect(nbsp(nocGroupLabel("fr", "63"))).toBe("63 : vente et services, FEER 3");
    expect(nocGroupLabel("en", "7")).toBe("7");
  });
});

describe("watchlist page", () => {
  it("renders a shell that reads as a document without scripts", async () => {
    const res = await get("/watchlist");
    expect(res.status).toBe(200);
    const page = await res.text();
    expect(page).toContain("<h1>Watchlist</h1>");
    expect(page).toContain("No employer is on the watchlist in this browser yet.");
    expect(page).toContain("<noscript> The watchlist is read from this browser&#39;s storage, which needs JavaScript.</noscript>");
    expect(page).toContain('<div id="watch-move" hidden="">');
    expect(page).toContain('<script src="/watchlist.js"></script>');
    expect(page).toContain(`data-max="${WATCH_MAX}"`);
    expect(page).toContain("LMIA Watch stores nothing about it");
    expect(page).toContain('<link rel="canonical" href="https://lmiawatch.ca/watchlist"');
  });

  it("hands its strings to the script in a JSON block, with no inline executable script", async () => {
    for (const lang of ["en", "fr"] as const) {
      const page = await html(`/watchlist?lang=${lang}`);
      for (const tag of page.match(/<script\b[^>]*>/g) ?? []) {
        expect(/\bsrc="|type="application\/(?:ld\+)?json"/.test(tag), tag).toBe(true);
      }
      const block = page.match(/<script type="application\/json" id="i18n">([\s\S]*?)<\/script>/)?.[1] ?? "";
      expect(block).not.toMatch(/[<>&]/);
      const data = JSON.parse(block) as { lang: string; locale: string; max: number; strings: Record<string, string> };
      expect(data.lang).toBe(lang);
      expect(data.max).toBe(WATCH_MAX);
      expect(Object.keys(data.strings)).toEqual([...WATCHLIST_CLIENT_KEYS]);
      for (const key of WATCHLIST_CLIENT_KEYS) expect(data.strings[key]).toBe(t(lang, key as Key));
    }
  });
});

describe("watch button on the profile", () => {
  it("carries its labels and stays hidden until the script shows it", async () => {
    const page = await html("/employers/emp-a000000001");
    expect(page).toContain('id="watch-toggle" data-employer="emp-a000000001"');
    expect(page).toContain('data-label-off="Watch" data-label-on="Watching"');
    expect(page).toContain(`data-label-full="Watchlist full (${WATCH_MAX})"`);
    expect(page).toContain('aria-pressed="false" style="display:none">Watch</button>');
    expect(page).toContain('<script src="/watchlist.js"></script>');
    const fr = await html("/employers/emp-a000000001?lang=fr");
    expect(fr).toContain('data-label-off="Suivre" data-label-on="Suivi en cours"');
  });
});

describe("watchlist.js", () => {
  const literalKeys = [...watchlistJs.matchAll(/\btxn?\("([^"]+)"(?:, "([^"]+)")?/g)].flatMap((m) => [m[1], m[2]]).filter(Boolean);
  const markKeys = [...watchlistJs.matchAll(/"(watch\.[a-z_]+)"/g)].map((m) => m[1]);

  it("asks only for strings its page supplies", () => {
    const keys = new Set<string>(WATCHLIST_CLIENT_KEYS);
    expect(literalKeys.length).toBeGreaterThan(10);
    for (const key of [...literalKeys, ...markKeys]) expect(keys.has(key), `watchlist.js uses ${key}`).toBe(true);
    for (const s of ["pending", "approved", "refused", "lapsed", "finding", "none"]) expect(keys.has(`status.${s}`)).toBe(true);
  });

  it("holds no English sentences of its own", () => {
    const sentences = [...watchlistJs.matchAll(/"((?:[^"\\]|\\.)*)"/g)].map((m) => m[1]).filter((s) => /\b[A-Z][a-z]+(?: [a-z]+)+/.test(s));
    expect(sentences).toEqual([]);
    expect(watchlistJs).not.toContain(EM_DASH);
    // Data reaches the page as text, never as markup.
    expect(watchlistJs).not.toMatch(/innerHTML|insertAdjacentHTML|document\.write/);
  });

  it("wraps every storage call", () => {
    const calls = watchlistJs.match(/localStorage\.\w+\(/g) ?? [];
    expect(calls.length).toBeGreaterThan(0);
    for (const line of watchlistJs.split("\n").filter((l) => /localStorage\.\w+\(/.test(l))) {
      expect(/try \{|^\s+localStorage\.(setItem|removeItem)\("watchlist-probe"/.test(line), line.trim()).toBe(true);
    }
  });
});

describe("French versions", () => {
  it("carry no leftover English, no unfilled placeholder and no em-dash", async () => {
    for (const path of ["/feeds?lang=fr", "/watchlist?lang=fr", "/employers/emp-a000000001?lang=fr"]) {
      const page = await html(path);
      expect(page, path).toContain('<html lang="fr">');
      for (const s of SENTINELS) expect(page, `${path} still says "${s}"`).not.toContain(s);
      const visible = page.replace(/<script type="application\/(?:ld\+)?json"[^>]*>[\s\S]*?<\/script>/g, "");
      expect(visible, path).not.toMatch(/\{\w+\}/);
      expect(page, path).not.toContain(EM_DASH);
    }
    const feeds = nbsp(await html("/feeds?lang=fr"));
    expect(feeds).toContain("<h1>Fils Atom</h1>");
    expect(feeds).toContain("Colombie-Britannique : Nouvelles offres en attente");
    expect(feeds).toContain("73 : métiers, transport, machinerie et domaines apparentés, FEER 3");
    expect(feeds).toContain("Agriculture primaire");
    const watch = nbsp(await html("/watchlist?lang=fr"));
    expect(watch).toContain("<h1>Liste de suivi</h1>");
    expect(watch).toContain("Aucun employeur n’est encore dans la liste de suivi de ce navigateur.");
  });

  it("keeps the sentinel list honest: each phrase is on an English page", async () => {
    const all = (await Promise.all(["/feeds", "/watchlist"].map((p) => html(p)))).join("\n");
    for (const s of SENTINELS) expect(all, s).toContain(s);
  });

  it("fits each page description in a result list", () => {
    for (const lang of ["en", "fr"] as const) {
      for (const key of ["feeds.description", "watch.description"] as const) {
        expect(t(lang, key).length, `${key} ${lang}`).toBeLessThanOrEqual(DESCRIPTION_MAX);
      }
    }
  });
});
