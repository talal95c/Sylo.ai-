import { cp, mkdir, rm, stat } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const specRoot = path.resolve(root, "../spec");
const sampleRoot = path.join(root, "samples");
const publicRoot = path.join(root, "public/spec");

async function isDirectory(directory) {
  try {
    return (await stat(directory)).isDirectory();
  } catch {
    return false;
  }
}

const hasSpec = await Promise.all([
  isDirectory(path.join(specRoot, "geo")),
  isDirectory(path.join(specRoot, "fixtures")),
]).then(([geo, fixtures]) => geo && fixtures);
const sourceRoot = hasSpec ? specRoot : sampleRoot;

await rm(publicRoot, { recursive: true, force: true });
await mkdir(publicRoot, { recursive: true });
await Promise.all(
  ["geo", "fixtures"].map((directory) =>
    cp(path.join(sourceRoot, directory), path.join(publicRoot, directory), {
      recursive: true,
    }),
  ),
);

console.log(`Synced ${hasSpec ? "spec" : "sample"} geo and fixtures from ${sourceRoot}`);
