// Usage: node scripts/check_bundle_budget.mjs <path-to-.next> <budget-kB-gzipped>
//
// Sums the gzipped size of every JS file the prerendered home page loads
// (its <script src> tags) and fails if that exceeds the budget. Only covers
// statically prerendered routes; extend to per-route manifests when the guest
// app gains dynamic routes.
import { readFileSync, existsSync } from "node:fs";
import { gzipSync } from "node:zlib";
import { join } from "node:path";

const [nextDir, budgetArg] = process.argv.slice(2);
const budgetKb = Number(budgetArg);
if (!nextDir || !Number.isFinite(budgetKb)) {
  console.error("usage: check_bundle_budget.mjs <.next dir> <budget kB gzipped>");
  process.exit(2);
}

const htmlPath = join(nextDir, "server", "app", "index.html");
if (!existsSync(htmlPath)) {
  console.error(`${htmlPath} not found; run \`pnpm --filter guest build\` first`);
  process.exit(2);
}

// noModule scripts are legacy polyfills that modern browsers never download.
const scripts = new Set(
  [...readFileSync(htmlPath, "utf8").matchAll(/<script\b[^>]*>/g)]
    .map((m) => m[0])
    .filter((tag) => !/\snoModule\b/i.test(tag))
    .map((tag) => /\ssrc="([^"]+)"/.exec(tag)?.[1])
    .filter(Boolean),
);

let totalBytes = 0;
for (const src of scripts) {
  const file = join(nextDir, src.replace(/^\/_next\//, "").split("?")[0]);
  if (!existsSync(file)) continue;
  const gz = gzipSync(readFileSync(file)).length;
  totalBytes += gz;
  console.log(`${(gz / 1024).toFixed(1).padStart(7)} kB  ${src}`);
}

const totalKb = totalBytes / 1024;
console.log(`first-load JS: ${totalKb.toFixed(1)} kB gzipped (budget ${budgetKb} kB)`);
if (totalKb > budgetKb) {
  console.error("Bundle budget exceeded");
  process.exit(1);
}
