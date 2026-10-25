import { describe, expect, it } from "vitest";
import { app } from "../src/index";
import { DOWNLOADS, LICENCE_ROWS } from "../src/pages/data";
import { testEnv } from "./assets";

const get = (path: string) => app.request(path, {}, testEnv());
const nbsp = (s: string) => s.replace(/[  ]/g, " ");
const EM_DASH = String.fromCharCode(0x2014);

// The licence section only, so a match elsewhere on the page cannot pass a check.
const licenceSection = (html: string) => html.slice(html.indexOf('<h2 id="licence">'), html.indexOf('<h2 id="changelog">'));

describe("data page licences", () => {
  it("gives each download its licence group", () => {
    const by = Object.fromEntries(DOWNLOADS.map((d) => [d.file, d.licence]));
    expect(by).toEqual({
      "pending_observations.csv": "canada",
      "approved_quarterly.csv": "ogl",
      "refused_quarterly.csv": "ogl",
      "employers.csv": "mixed",
      "indicators.csv": "mixed",
      "findings.csv": "canada",
      "esdc_resources.csv": "ogl",
    });
    expect(LICENCE_ROWS.length).toBe(13);
  });

  it("states the licence per source in English, with no blanket relicensing", async () => {
    const html = await (await get("/data")).text();
    expect(html).not.toContain("released under the same licence");
    expect(html).not.toContain("Derived files on this site");
    const lic = licenceSection(html);
    expect(lic).toContain("Each file and field keeps the licence or terms of the source it comes from.");
    // Files derived only from ESDC's lists: the OGL.
    expect(lic).toContain("approved_quarterly.csv, refused_quarterly.csv, esdc_resources.csv and the mirrored ESDC files");
    expect(lic).toContain('<a href="https://open.canada.ca/en/open-government-licence-canada">Open Government Licence, Canada</a>: reuse, commercial or not, with attribution.');
    // Job Bank and IRCC material: canada.ca's terms.
    expect(lic).toContain("pending_observations.csv; in employers.csv, pending_count");
    expect(lic).toContain(
      'Under the <a href="https://www.canada.ca/en/transparency/terms.html">Government of Canada terms of use (canada.ca)</a>: non-commercial reproduction with attribution; commercial redistribution needs ESDC&#39;s written permission.',
    );
    expect(lic).toContain("findings.csv (IRCC&#39;s list of non-compliant employers)");
    expect(lic).toContain('Under the same <a href="https://www.canada.ca/en/transparency/terms.html">');
    // Quebec register: CC BY-NC-SA 4.0 with the Registraire's citation.
    expect(lic).toContain('<a href="https://creativecommons.org/licenses/by-nc-sa/4.0/">CC BY-NC-SA 4.0</a>');
    expect(lic).toContain("REGISTRAIRE DES ENTREPRISES. Registre des entreprises, [Jeu de données], dans Données Québec.");
    // Statistics Canada: its licence and source notice.
    expect(lic).toContain('<a href="https://www.statcan.gc.ca/en/reference/licence">Statistics Canada Open Licence</a>');
    expect(lic).toContain("Reproduced and distributed on an &quot;as is&quot; basis with the permission of Statistics Canada.");
    expect(lic).toContain("this does not constitute an endorsement by Statistics Canada of this product.");
    expect(lic).toContain("GeoNames, under CC BY 4.0.");
    expect(lic).not.toContain(EM_DASH);
  });

  it("shows each download's licence beside it", async () => {
    const html = await (await get("/data")).text();
    // The table row, not the JSON-LD block, which names the same paths.
    const row = (file: string) => {
      const at = html.indexOf(`<a href="/downloads/${file}"`);
      return html.slice(at, html.indexOf("</tr>", at));
    };
    expect(row("approved_quarterly.csv")).toContain('<a href="#licence">Open Government Licence, Canada</a>');
    expect(row("pending_observations.csv")).toContain('<a href="#licence">canada.ca terms, non-commercial</a>');
    expect(row("findings.csv")).toContain('<a href="#licence">canada.ca terms, non-commercial</a>');
    expect(row("employers.csv")).toContain('<a href="#licence">By source</a>');
  });

  it("says the same in French", async () => {
    const html = nbsp(await (await get("/data?lang=fr")).text());
    const lic = licenceSection(html);
    expect(lic).toContain("Chaque fichier et chaque champ garde la licence ou les conditions de la source dont il provient.");
    expect(lic).toContain('<a href="https://ouvert.canada.ca/fr/licence-du-gouvernement-ouvert-canada">Licence du gouvernement ouvert, Canada</a> : réutilisation');
    expect(lic).toContain(
      'Selon les <a href="https://www.canada.ca/fr/transparence/avis.html">conditions d’utilisation du gouvernement du Canada (canada.ca)</a> : reproduction non commerciale avec mention de la source; la redistribution commerciale exige la permission écrite d’EDSC.',
    );
    expect(lic).toContain('<a href="https://creativecommons.org/licenses/by-nc-sa/4.0/deed.fr">CC BY-NC-SA 4.0</a>');
    expect(lic).toContain("Citation : REGISTRAIRE DES ENTREPRISES. Registre des entreprises, [Jeu de données], dans Données Québec.");
    expect(lic).toContain("Reproduit et diffusé « tel quel » avec la permission de Statistique Canada.");
    expect(lic).toContain("ceci ne constitue pas une approbation de ce produit par Statistique Canada.");
    expect(html).toContain('<a href="#licence">conditions de canada.ca, usage non commercial</a>');
    expect(html).not.toContain("Les fichiers dérivés de ce site");
    expect(lic).not.toContain(EM_DASH);
  });
});
