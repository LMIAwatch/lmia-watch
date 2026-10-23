// Small checks for the JSON files the pages render. The pipeline writes every
// file, but a page that renders a field of the wrong type throws (a string has
// no .map, null has no fields), so each page checks the fields it reads and
// treats a file that fails as missing: "not published" or "not found", never a
// server error.

export const isObj = (v: unknown): v is Record<string, any> => !!v && typeof v === "object" && !Array.isArray(v);
export const isNum = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
export const isStr = (v: unknown): v is string => typeof v === "string";
export const isBool = (v: unknown): v is boolean => typeof v === "boolean";
// The export writes null where there is nothing to show.
export const isNumOrNull = (v: unknown): v is number | null => v === null || isNum(v);
export const isStrOrNull = (v: unknown): v is string | null => v === null || isStr(v);
// A key the export leaves out on some files (a province page has no LFS rate).
export const optional = (v: unknown, check: (x: unknown) => boolean): boolean => v === undefined || check(v);
// One unreadable element makes the list unusable: a table with a row missing
// would misstate the file.
export const isListOf = (v: unknown, each: (x: any) => boolean): v is any[] => Array.isArray(v) && v.every((x) => each(x));
