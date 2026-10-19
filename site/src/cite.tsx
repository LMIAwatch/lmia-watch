import type { FC } from "hono/jsx";
import type { Citation } from "./data";
import { t, tj, type Lang } from "./i18n";

// The "How to cite" block on the Data and Methodology pages. It renders
// nothing until the nightly run has published a Zenodo record and written its
// DOIs into stats.json, so the pages never show an empty or placeholder
// citation. The DOIs come from our own export but are still checked for shape
// before they become links.

const DOI = /^10\.\d{4,9}\/[A-Za-z0-9._;()/:-]+$/;

export function validCitation(c: Citation | null | undefined): Citation | null {
  if (!c || typeof c !== "object" || typeof c.concept_doi !== "string" || !DOI.test(c.concept_doi)) return null;
  return c;
}

const DoiLink: FC<{ doi: string }> = ({ doi }) => <a href={`https://doi.org/${doi}`}>{`https://doi.org/${doi}`}</a>;

export const HowToCite: FC<{ lang: Lang; citation: Citation | null | undefined }> = ({ lang, citation }) => {
  const c = validCitation(citation);
  if (!c) return null;
  const version = typeof c.doi === "string" && DOI.test(c.doi) ? c.doi : c.concept_doi;
  const year = (c.published ?? "").slice(0, 4) || (c.version ?? "").slice(0, 4);
  return (
    <>
      <h2 id="cite">{t(lang, "cite.title")}</h2>
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
