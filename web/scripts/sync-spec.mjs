#!/usr/bin/env node
// Copies ../spec/geo and ../spec/fixtures into public/spec/ (git-ignored), so the web app can
// import the geography and replay the recorded events. Runs before dev, build, typecheck and test.
//
// - spec/geo is required (lib/geo.ts imports institutions.json): the script fails if it is missing.
// - spec/fixtures may be empty or missing: the script only warns, and replay mode reports it in the UI.

import { cpSync, existsSync, mkdirSync, readdirSync, rmSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const webRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const specRoot = path.resolve(webRoot, "..", "spec");
const outRoot = path.join(webRoot, "public", "spec");

/** Mirrors one folder of /spec into public/spec and returns the number of files copied. */
function mirror(name) {
  const source = path.join(specRoot, name);
  const target = path.join(outRoot, name);
  rmSync(target, { recursive: true, force: true });
  mkdirSync(target, { recursive: true });
  if (!existsSync(source)) return -1;
  cpSync(source, target, { recursive: true });
  return readdirSync(target, { recursive: true }).length;
}

const geo = mirror("geo");
if (geo < 0 || !existsSync(path.join(outRoot, "geo", "institutions.json"))) {
  console.error(`[sync-spec] ${path.join(specRoot, "geo", "institutions.json")} is missing: the web app cannot build without it.`);
  process.exit(1);
}

const fixtures = mirror("fixtures");
if (fixtures <= 0) {
  console.warn("[sync-spec] no recorded fixtures in ../spec/fixtures: replay mode will have nothing to play (run `make fixtures`).");
}

console.log(`[sync-spec] public/spec: geo (${geo} file${geo === 1 ? "" : "s"}), fixtures (${Math.max(fixtures, 0)} file${fixtures === 1 ? "" : "s"})`);
