import type { FC } from "hono/jsx";
import type { Citation } from "./data";
import { numberLocale, t, tj, type Key, type Lang } from "./i18n";
import { SITE_NAME, SITE_ORIGIN } from "./seo";

// The "How to cite" block on the Data and Methodology pages. It renders
// nothing until the nightly run has published a Zenodo record and written its
// DOIs into stats.json, so the pages never show an empty or placeholder
// citation. The DOIs come from our own export but are still checked for shape
// before they become links.

const DOI = /^10\.\d{4,9}\/[A-Za-z0-9._;()/:-]+$/;

// The other fields are printed as text (the year is cut from published or
// version), so a record with one of another type is treated as absent too.
const isTextOrNone = (v: unknown): boolean => v == null || typeof v === "string";

export function validCitation(c: Citation | null | undefined): Citation | null {
  if (!c || typeof c !== "object" || typeof c.concept_doi !== "string" || !DOI.test(c.concept_doi)) return null;
  if (typeof c.title !== "string" || ![c.doi, c.version, c.published].every(isTextOrNone)) return null;
  return c;
}

// The version DOI when it is well formed, else the concept DOI.
export function citationDoi(c: Citation): string {
  return typeof c.doi === "string" && DOI.test(c.doi) ? c.doi : c.concept_doi;
}

export function citationYear(c: Citation): string {
  return (c.published ?? "").slice(0, 4) || (c.version ?? "").slice(0, 4);
}

const DoiLink: FC<{ doi: string }> = ({ doi }) => <a href={`https://doi.org/${doi}`}>{`https://doi.org/${doi}`}</a>;

// The /cite page places the block under a heading of its own (heading={false}).
export const HowToCite: FC<{ lang: Lang; citation: Citation | null | undefined; heading?: boolean }> = ({
  lang, citation, heading = true,
}) => {
  const c = validCitation(citation);
  if (!c) return null;
  const version = citationDoi(c);
  const year = citationYear(c);
  return (
    <>
      {heading && <h2 id="cite">{t(lang, "cite.title")}</h2>}
      <p>{t(lang, "cite.text")}</p>
      <p style="overflow-wrap:anywhere">
        {tj(lang, "cite.reference", {
          author: "LMIA Watch",
          year: year || (lang === "fr" ? "s.d." : "n.d."),
          title: <cite>{c.title}</cite>,
          version: c.version ?? "",
          doi: <DoiLink doi={version} />,
        })}
      </p>
      {version !== c.concept_doi && (
        <p class="muted small" style="overflow-wrap:anywhere">{tj(lang, "cite.concept", { doi: <DoiLink doi={c.concept_doi} /> })}</p>
      )}
    </>
  );
};

// --- The /cite page's formats ----------------------------------------------
// The website in four prose styles and two machine formats, and the Zenodo
// deposit in the two machine formats (HowToCite above gives its APA form).

export type Style = "apa" | "mla" | "chicago" | "harvard" | "bibtex" | "ris";
type ProseStyle = Exclude<Style, "bibtex" | "ris">;

export const STYLE_LABEL: Record<Style, Key> = {
  apa: "citepage.style.apa",
  mla: "citepage.style.mla",
  chicago: "citepage.style.chicago",
  harvard: "citepage.style.harvard",
  bibtex: "citepage.style.bibtex",
  ris: "citepage.style.ris",
};

// A calendar date in ISO form, or null. The year and the written dates are
// cut from it, so a value such as 2026-13-45 must not roll into another date.
export function isoDate(v: unknown): string | null {
  if (typeof v !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(v)) return null;
  const d = new Date(`${v}T00:00:00Z`);
  return !Number.isNaN(d.getTime()) && d.toISOString().slice(0, 10) === v ? v : null;
}

// October 12, 2026 (APA, Chicago), 12 Oct. 2026 (MLA), 12 October 2026
// (Harvard). French writes 12 octobre 2026 (MLA: 12 oct. 2026) and 1er for
// the first of the month.
export function styleDate(iso: string, lang: Lang, style: ProseStyle): string {
  const fr = lang === "fr";
  const parts = new Intl.DateTimeFormat(numberLocale(lang), {
    day: "numeric", month: fr && style === "mla" ? "short" : "long", year: "numeric", timeZone: "UTC",
  }).formatToParts(new Date(`${iso}T00:00:00Z`));
  const part = (type: string) => parts.find((p) => p.type === type)?.value ?? "";
  const day = part("day");
  const year = part("year");
  let month = part("month");
  if (fr) return `${day === "1" ? "1er" : day} ${month} ${year}`;
  // MLA shortens every month name longer than four letters, September to Sept.
  if (style === "mla" && month.length > 4) month = month === "September" ? "Sept." : `${month.slice(0, 3)}.`;
  return style === "mla" || style === "harvard" ? `${day} ${month} ${year}` : `${month} ${day}, ${year}`;
}

// The machine formats keep plain spaces and straight apostrophes: the French
// typography's no-break spaces trip LaTeX and some importers.
const plain = (s: string) => s.replace(/[\u00a0\u202f]/g, " ").replace(/\u2019/g, "'");
// A brace or backslash would end or break a BibTeX field; the other
// characters LaTeX reads as commands are escaped.
const tex = (s: string) => s.replace(/[\\{}]/g, "").replace(/([&%$#_])/g, "\\$1");
const risDate = (iso: string) => iso.replace(/-/g, "/");

function bibtex(type: string, key: string, fields: [string, string | null][]): string {
  const kept = fields.filter((f): f is [string, string] => !!f[1]);
  const width = Math.max(...kept.map(([name]) => name.length));
  return [`@${type}{${key},`, ...kept.map(([name, v]) => `  ${name.padEnd(width)} = {${v}},`), "}"].join("\n");
}

function ris(type: string, fields: [string, string | null][]): string {
  const kept = fields.filter((f): f is [string, string] => !!f[1]);
  return [`TY  - ${type}`, ...kept.map(([tag, v]) => `${tag}  - ${v.replace(/\s+/g, " ")}`), "ER  - "].join("\n");
}

export function websiteCitations(lang: Lang, dataAsOf: string, accessed: string): { style: Style; body: unknown }[] {
  const year = dataAsOf.slice(0, 4);
  const data = (style: ProseStyle) => t(lang, "citepage.data_as_of", { date: styleDate(dataAsOf, lang, style) });
  const on = (style: ProseStyle) => styleDate(accessed, lang, style);
  const italic = (key: Key) => <i>{t(lang, key)}</i>;
  const author = SITE_NAME;
  const url = SITE_ORIGIN;
  const title = plain(t(lang, "citepage.site_title"));
  const note = plain(t(lang, "citepage.data_as_of", { date: dataAsOf }));
  return [
    {
      style: "apa",
      body: tj(lang, "citepage.fmt.apa", { author, year, title: italic("citepage.site_title_sentence"), data: data("apa"), accessed: on("apa"), url }),
    },
    // MLA starts with the title when the author is also the site, and leaves the scheme off the address.
    {
      style: "mla",
      body: tj(lang, "citepage.fmt.mla", { title: italic("citepage.site_title_headline"), data: data("mla"), url: new URL(url).host, accessed: on("mla") }),
    },
    // Chicago sets the title of a whole website in roman type.
    {
      style: "chicago",
      body: tj(lang, "citepage.fmt.chicago", { author, year, title: t(lang, "citepage.site_title_headline"), data: data("chicago"), accessed: on("chicago"), url }),
    },
    {
      style: "harvard",
      body: tj(lang, "citepage.fmt.harvard", { author, year, title: italic("citepage.site_title"), data: data("harvard"), accessed: on("harvard"), url }),
    },
    // The double braces keep the author whole (not "Watch, L.") and the title's capitals as written.
    {
      style: "bibtex",
      body: bibtex("misc", `lmiawatch${year}`, [
        ["author", `{${author}}`],
        ["title", `{${tex(title)}}`],
        ["year", year],
        ["howpublished", `\\url{${url}}`],
        ["note", tex(note)],
        ["urldate", accessed],
      ]),
    },
    {
      style: "ris",
      body: ris("ELEC", [
        ["TI", title],
        ["AU", author],
        ["PY", year],
        ["DA", risDate(dataAsOf)],
        ["UR", url],
        ["Y2", risDate(accessed)],
        ["N1", note],
      ]),
    },
  ];
}

export function datasetBibtex(c: Citation): string {
  const doi = citationDoi(c);
  const year = citationYear(c);
  return bibtex("dataset", `lmiawatch${/^\d{4}$/.test(year) ? year : ""}data`, [
    ["author", `{${SITE_NAME}}`],
    ["title", `{${tex(plain(c.title))}}`],
    ["year", tex(year)],
    ["version", c.version ? tex(c.version) : null],
    ["publisher", "Zenodo"],
    ["doi", doi],
    ["url", `https://doi.org/${doi}`],
  ]);
}

export function datasetRis(c: Citation): string {
  const doi = citationDoi(c);
  return ris("DATA", [
    ["TI", plain(c.title)],
    ["AU", SITE_NAME],
    ["PY", citationYear(c)],
    ["ET", c.version],
    ["PB", "Zenodo"],
    ["DO", doi],
    ["UR", `https://doi.org/${doi}`],
  ]);
}
