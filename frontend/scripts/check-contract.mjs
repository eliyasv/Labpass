import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import openapiTS, { astToString } from "openapi-typescript";

const root = fileURLToPath(new URL("../../", import.meta.url));
const python = process.env.LABPASS_PYTHON || `${root}.venv/bin/python`;
execFileSync(
  python,
  [
    `${root}scripts/export-openapi.py`,
    `${root}frontend/openapi.json`,
    "--check",
  ],
  { stdio: "inherit" },
);
const generated = astToString(
  await openapiTS(new URL("../openapi.json", import.meta.url)),
);
const committed = readFileSync(
  new URL("../src/generated/api.ts", import.meta.url),
  "utf8",
);
// The CLI adds a generated-file header; compare the actual declarations.
if (
  committed.slice(committed.indexOf("export interface paths")) !==
  generated.slice(generated.indexOf("export interface paths"))
) {
  throw new Error(
    "Generated TypeScript types are stale. Run npm run generate.",
  );
}
console.log("Generated TypeScript types match the API contract");
