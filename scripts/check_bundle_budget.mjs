// Usage: node scripts/check_bundle_budget.mjs <path-to-.next> <budget-kB-gzipped>
//
// For every route a guest can load, sums the gzipped size of the JS it downloads
// and fails if the largest exceeds the budget.
//   - Prerendered pages: the <script src> tags of their HTML.
//   - Dynamic routes (the QR landing): the scripts of the home page (the shared
//     framework chunks every page loads) plus the route's own entry chunks from its
//     client-reference manifest. An approximation, deliberately on the strict side.
import { readFileSync, existsSync, readdirSync } from "node:fs";
import { gzipSync } from "node:zlib";
import { join } from "node:path";

const [nextDir, budgetArg] = process.argv.slice(2);
const budgetKb = Number(budgetArg);
if (!nextDir || !Number.isFinite(budgetKb)) {
  console.error("usage: check_bundle_budget.mjs <.next dir> <budget kB gzipped>");
  process.exit(2);
}

const appDir = join(nextDir, "server", "app");
if (!existsSync(join(appDir, "index.html"))) {
  console.error(`${appDir}/index.html not found; run \`pnpm --filter guest build\` first`);
  process.exit(2);
}

function scriptsOf(htmlPath) {
  // noModule scripts are legacy polyfills that modern browsers never download.
  return [...readFileSync(htmlPath, "utf8").matchAll(/<script\b[^>]*>/g)]
    .map((m) => m[0])
    .filter((tag) => !/\snoModule\b/i.test(tag))
    .map((tag) => /\ssrc="([^"]+)"/.exec(tag)?.[1])
    .filter(Boolean)
    .map((src) => src.replace(/^\/_next\//, "").split("?")[0]);
}

function gzKb(scripts) {
  let bytes = 0;
  for (const src of scripts) {
    const file = join(nextDir, src);
    if (existsSync(file)) bytes += gzipSync(readFileSync(file)).length;
  }
  return bytes / 1024;
}

const routes = new Map();
for (const name of readdirSync(appDir).filter((f) => f.endsWith(".html"))) {
  if (name.startsWith("_")) continue; // _not-found, _global-error
  routes.set(name === "index.html" ? "/" : `/${name.slice(0, -5)}`, scriptsOf(join(appDir, name)));
}

const shared = routes.get("/") ?? [];
const walk = (dir) =>
  readdirSync(dir, { withFileTypes: true }).flatMap((e) =>
    e.isDirectory() ? walk(join(dir, e.name)) : [join(dir, e.name)],
  );
for (const file of walk(appDir).filter((f) => f.endsWith("page_client-reference-manifest.js"))) {
  const route = file.slice(appDir.length, -"/page_client-reference-manifest.js".length) || "/";
  if (routes.has(route) || route.includes("(") || route.startsWith("/_")) continue;
  const text = readFileSync(file, "utf8");
  const entry = /"entryJSFiles":\s*(\{.*?\})\s*[,}]/s.exec(text)?.[1];
  const own = entry ? Object.values(JSON.parse(entry)).flat() : [];
  routes.set(route, [...new Set([...shared, ...own])]);
}

let worst = 0;
for (const [route, scripts] of routes) {
  const kb = gzKb(new Set(scripts));
  worst = Math.max(worst, kb);
  console.log(`${kb.toFixed(1).padStart(7)} kB  ${route}`);
}
console.log(`first-load JS: ${worst.toFixed(1)} kB gzipped, largest route (budget ${budgetKb} kB)`);
if (worst > budgetKb) {
  console.error("Bundle budget exceeded");
  process.exit(1);
}
