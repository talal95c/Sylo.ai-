// Copies the shared spec files the browser needs (geography and fixtures) into public/spec.
// public/spec is git-ignored: /spec stays the single source of truth.
import { cpSync, existsSync, mkdirSync, rmSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const webDir = join(dirname(fileURLToPath(import.meta.url)), "..");
const specDir = join(webDir, "..", "spec");
const target = join(webDir, "public", "spec");

for (const folder of ["geo", "fixtures"]) {
  const source = join(specDir, folder);
  if (!existsSync(source)) {
    console.error(`sync-spec: ${source} is missing`);
    process.exit(1);
  }
}

rmSync(target, { recursive: true, force: true });
mkdirSync(target, { recursive: true });
for (const folder of ["geo", "fixtures"]) {
  cpSync(join(specDir, folder), join(target, folder), { recursive: true });
}
console.log("sync-spec: copied spec/geo and spec/fixtures to public/spec");
