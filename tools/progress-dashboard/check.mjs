#!/usr/bin/env node
/**
 * tools/progress-dashboard/check.mjs — dashboard drift guard.
 *
 * Fails (exit 1) when tools/progress-dashboard/dist/ does not match a fresh
 * re-read of docs/implementation-status.json:
 *
 *   1. dist/project-data.js summary counts / task rows vs the ledger
 *      (catches hand-edits of the generated data file);
 *   2. dist/index.html vs tools/progress-dashboard/index.html
 *      (catches edits to the page that were never rebuilt into dist/).
 *
 * The `source` sha in project-data.js records the HEAD the dist was built
 * at and is only format-checked: it intentionally lags HEAD once dist is
 * committed (a commit cannot contain its own hash), and ledger staleness
 * is already caught by the content comparison above.
 *
 * Usage: npm run check:dashboard   (or: node tools/progress-dashboard/check.mjs)
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { buildProject } from "./build.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..", "..");
const LEDGER_PATH = join(root, "docs", "implementation-status.json");
const INDEX_SRC = join(here, "index.html");
const DIST_DATA = join(here, "dist", "project-data.js");
const DIST_INDEX = join(here, "dist", "index.html");
const SOURCE_PREFIX = "docs/implementation-status.json@";

const failures = [];

function fail(msg) {
  failures.push(msg);
}

function loadDistProject() {
  let code;
  try {
    code = readFileSync(DIST_DATA, "utf8");
  } catch {
    fail(`dist/project-data.js is missing — run "npm run build:dashboard"`);
    return null;
  }
  try {
    const sandbox = { window: {} };
    // project-data.js is a plain script: `window.LUMIRSS_PROJECT = {...}`
    new Function("window", `${code}\nreturn window.LUMIRSS_PROJECT;`)(sandbox.window);
    return sandbox.window.LUMIRSS_PROJECT;
  } catch (err) {
    fail(`dist/project-data.js is not valid JS: ${err.message}`);
    return null;
  }
}

function diffProject(expected, actual) {
  const summary = actual.summary ?? {};
  for (const key of ["pTotal", "nTotal", "verifiedPct"]) {
    if (expected.summary[key] !== summary[key]) {
      fail(
        `summary.${key}: dist says ${JSON.stringify(summary[key])}, ledger says ${JSON.stringify(expected.summary[key])}` +
          ` — run "npm run build:dashboard"`,
      );
    }
  }
  for (const key of ["pByStatus", "nByStatus", "nNovelty"]) {
    diff(expected.summary[key], summary[key], `summary.${key}`);
  }
  const actualTasks = Array.isArray(actual.tasks) ? actual.tasks : [];
  if (actualTasks.length !== expected.tasks.length) {
    fail(
      `tasks: dist has ${actualTasks.length} rows, ledger has ${expected.tasks.length} — run "npm run build:dashboard"`,
    );
  }
  const pairs = expected.tasks.map((t, i) => [t, actualTasks[i]]);
  let shown = 0;
  for (const [exp, act] of pairs) {
    if (shown >= 5) {
      fail(`tasks: more row mismatches hidden — run "npm run build:dashboard"`);
      break;
    }
    const before = failures.length;
    diff(exp, act, `task ${exp.id}`);
    if (failures.length > before) shown += 1;
  }
}

function diff(expected, actual, path) {
  if (JSON.stringify(expected) === JSON.stringify(actual)) return;
  fail(
    `${path}: dist says ${JSON.stringify(actual)}, ledger says ${JSON.stringify(expected)}` +
      ` — dist/project-data.js was hand-edited or stale; run "npm run build:dashboard"`,
  );
}

const ledger = JSON.parse(readFileSync(LEDGER_PATH, "utf8"));
const actual = loadDistProject();

if (actual) {
  if (typeof actual.source !== "string" || !actual.source.startsWith(SOURCE_PREFIX)) {
    fail(`source: expected "${SOURCE_PREFIX}<sha>", got ${JSON.stringify(actual.source)}`);
  } else {
    diffProject(buildProject(ledger, actual.source.slice(SOURCE_PREFIX.length)), actual);
  }
}

let srcIndex;
let distIndex;
try {
  srcIndex = readFileSync(INDEX_SRC);
} catch {
  srcIndex = null;
}
try {
  distIndex = readFileSync(DIST_INDEX);
} catch {
  distIndex = null;
}
if (!srcIndex) {
  fail("tools/progress-dashboard/index.html is missing");
} else if (!distIndex) {
  fail('dist/index.html is missing — run "npm run build:dashboard"');
} else if (!srcIndex.equals(distIndex)) {
  fail(
    "dist/index.html differs from tools/progress-dashboard/index.html — page was edited without rebuilding; run \"npm run build:dashboard\"",
  );
}

if (failures.length > 0) {
  for (const f of failures) process.stderr.write(`FAIL: ${f}\n`);
  process.stderr.write(
    `check:dashboard: ${failures.length} problem(s) — dashboard dist/ is out of sync with docs/implementation-status.json\n`,
  );
  process.exit(1);
}
process.stdout.write(
  `check:dashboard OK — dist/ matches the ledger` +
    (actual ? ` (${actual.tasks.length} tasks, ${actual.source})` : "") +
    "\n",
);
