#!/usr/bin/env node
/**
 * tools/progress-dashboard/build.mjs — progress dashboard generator.
 *
 * Reads docs/implementation-status.json (the task ledger, source of truth)
 * and emits a standalone, deployable dashboard into
 * tools/progress-dashboard/dist/:
 *
 *   - dist/project-data.js  (window.LUMIRSS_PROJECT consumed by index.html)
 *   - dist/index.html       (byte copy of tools/progress-dashboard/index.html)
 *
 * Zero dependencies (Node stdlib only). Deterministic output: tasks are
 * sorted by id, count-map keys are sorted, and generatedAt mirrors the
 * ledger's own generated_at — the same ledger at the same HEAD commit
 * always produces a byte-identical dist/project-data.js.
 *
 * Usage: npm run build:dashboard   (or: node tools/progress-dashboard/build.mjs)
 * Check: npm run check:dashboard   (drift guard — see check.mjs)
 */
import { execFileSync } from "node:child_process";
import { copyFileSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..", "..");
const LEDGER_PATH = join(root, "docs", "implementation-status.json");
const INDEX_SRC = join(here, "index.html");
const DIST_DIR = join(here, "dist");
const SCHEMA = "lumirss-implementation-status/v1";

/** Short HEAD sha of this repository (fails loudly outside a git repo). */
export function shortSha() {
  return execFileSync("git", ["rev-parse", "--short", "HEAD"], {
    cwd: root,
    encoding: "utf8",
  }).trim();
}

function sortedCounts(counts) {
  return Object.fromEntries(
    Object.entries(counts).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0)),
  );
}

/**
 * Compact task rows + summary counts derived from the ledger.
 * Exported so check.mjs re-uses the exact same logic (no drift).
 */
export function summarize(ledger) {
  const tasks = sortedTasks(ledger);
  const pByStatus = {};
  const nByStatus = {};
  const nNovelty = { exists: 0, partial: 0, new: 0 };
  let verified = 0;
  for (const t of tasks) {
    for (const field of ["id", "title", "phase", "status"]) {
      if (typeof t[field] !== "string" || t[field] === "") {
        throw new Error(
          `ledger task is missing a valid "${field}": ${JSON.stringify(t.id ?? t)}`,
        );
      }
    }
    if (t.phase === "P") pByStatus[t.status] = (pByStatus[t.status] ?? 0) + 1;
    if (t.phase === "N") {
      nByStatus[t.status] = (nByStatus[t.status] ?? 0) + 1;
      const novelty = String(t.novelty ?? "").toLowerCase();
      if (novelty === "exists" || novelty === "partial" || novelty === "new") {
        nNovelty[novelty] += 1;
      }
    }
    if (t.status === "verified" || t.status === "deployed_verified") verified += 1;
  }
  return {
    pTotal: tasks.filter((t) => t.phase === "P").length,
    nTotal: tasks.filter((t) => t.phase === "N").length,
    pByStatus: sortedCounts(pByStatus),
    nByStatus: sortedCounts(nByStatus),
    nNovelty: { exists: nNovelty.exists, partial: nNovelty.partial, new: nNovelty.new },
    verifiedPct: Math.round((verified / tasks.length) * 1000) / 10,
  };
}

function sortedTasks(ledger) {
  return [...ledger.tasks].sort((a, b) =>
    a.id < b.id ? -1 : a.id > b.id ? 1 : 0,
  );
}

/** The full window.LUMIRSS_PROJECT payload. */
export function buildProject(ledger, sha) {
  const tasks = sortedTasks(ledger).map((t) => ({
    id: t.id,
    title: t.title,
    phase: t.phase,
    status: t.status,
    novelty: t.novelty ?? null,
  }));
  return {
    generatedAt: ledger.generated_at,
    source: `docs/implementation-status.json@${sha}`,
    summary: summarize(ledger),
    tasks,
  };
}

function main() {
  const ledger = JSON.parse(readFileSync(LEDGER_PATH, "utf8"));
  if (ledger.schema !== SCHEMA) {
    throw new Error(
      `unexpected ledger schema ${JSON.stringify(ledger.schema)} (want ${SCHEMA}) — update ${JSON.stringify("tools/progress-dashboard/build.mjs")} first`,
    );
  }
  if (!Array.isArray(ledger.tasks) || ledger.tasks.length === 0) {
    throw new Error("ledger has no tasks — refusing to emit an empty board");
  }
  if (typeof ledger.generated_at !== "string" || ledger.generated_at === "") {
    throw new Error('ledger is missing "generated_at"');
  }

  const project = buildProject(ledger, shortSha());
  const js =
    "// AUTO-GENERATED — DO NOT EDIT. Regenerate with: npm run build:dashboard\n" +
    "// Source of truth: docs/implementation-status.json (task ledger).\n" +
    "// Consumed by index.html (window.LUMIRSS_PROJECT). Compact rows only.\n" +
    `window.LUMIRSS_PROJECT = ${JSON.stringify(project, null, 2)};\n`;

  mkdirSync(DIST_DIR, { recursive: true });
  writeFileSync(join(DIST_DIR, "project-data.js"), js);
  copyFileSync(INDEX_SRC, join(DIST_DIR, "index.html"));
  process.stdout.write(
    `dashboard: dist/project-data.js (${project.tasks.length} tasks, ` +
      `${project.summary.pTotal} P / ${project.summary.nTotal} N, ` +
      `verified ${project.summary.verifiedPct}%) + dist/index.html (${project.source})\n`,
  );
}

if (
  process.argv[1] &&
  import.meta.url === pathToFileURL(process.argv[1]).href
) {
  main();
}
