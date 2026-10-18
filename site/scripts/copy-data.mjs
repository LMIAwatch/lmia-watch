// Copies the pipeline's static export into public/data for local development.
import { cpSync, existsSync, rmSync } from "node:fs";
const src = new URL("../../data/out/static/", import.meta.url);
const dst = new URL("../public/data/", import.meta.url);
if (!existsSync(src)) {
  console.error("No export found at data/out/static. Run the pipeline's export stage first.");
  process.exit(1);
}
rmSync(dst, { recursive: true, force: true });
cpSync(src, dst, { recursive: true });
console.log("copied data/out/static to site/public/data");
