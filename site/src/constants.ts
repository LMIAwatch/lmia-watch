import { provinceName } from "./i18n";

export const STATUSES = ["pending", "approved", "refused", "lapsed"];
export const PROVINCES = ["AB", "BC", "MB", "NB", "NL", "NS", "NT", "NU", "ON", "PE", "QC", "SK", "YT", "XX"];
// ESDC's stream names as published; they are also the filter values in search
// URLs. streamLabel() in i18n.ts gives the name in the reader's language.
export const STREAMS = ["High Wage", "Low Wage", "Primary Agriculture", "Global Talent Stream", "Permanent Resident Only"];
export const INDICATORS = [
  "newly_incorporated",
  "repeat_applicant",
  "wage_at_floor",
  "low_wage_high_unemployment",
  "high_volume",
  "refused_then_reposted",
];
// English names; provinceName(lang, code) in i18n.ts gives either language.
export const PROVINCE_NAME: Record<string, string> = Object.fromEntries(PROVINCES.map((p) => [p, provinceName("en", p)]));
export const PAGE_SIZE = 25;
