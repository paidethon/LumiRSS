#!/usr/bin/env node
/**
 * Server-side mixed-load / soak driver for the LumiRSS BFF (P10).
 *
 * Zero dependencies beyond the Node stdlib (node >= 18). Drives the
 * PRODUCTION-LIKE e2e stack (e2e/stack/docker-compose.e2e.yml) over the
 * same entry point a browser uses (web/Caddy at BASE_URL), with a FIXED
 * authenticated scenario mix per loop iteration:
 *
 *   60%  list entries          GET  /api/v1/entries
 *   20%  open entry detail     GET  /api/v1/entries/{entryRef}
 *   10%  search query          GET  /api/v1/search?q=...&limit=20
 *   10%  workspace list +      GET  /api/v1/workspaces
 *        add/remove item       POST   /api/v1/workspaces/{id}/items
 *                              DELETE /api/v1/workspaces/{id}/items/{ref}
 *
 * Phases: warmup (default 60s, discarded) -> steady (DURATION_S, the
 * measured window) -> report. Login happens once; the session cookie is
 * reused and refreshed via re-login on 401. Alongside the HTTP load, the
 * BFF container is sampled on a ~1s target cadence with
 * `docker stats --no-stream` (best-effort: a missing docker binary or
 * container degrades to statsAvailable=false, never fails the run; each
 * CLI spawn takes ~1-2s itself, so the effective period is ~2s and the
 * sample count in the report reflects that honestly).
 *
 * Memory discipline: latency percentiles come from fixed-size log2
 * bucketed histograms (per endpoint x phase); container samples are
 * aggregated incrementally, and the retained series is decimated in place
 * so it never exceeds STATS_MAX_POINTS entries. Nothing grows with the
 * request count.
 *
 * Output: tools/perf/reports/soak-<ts>.json + a human summary on stdout.
 * SIGINT cancels the run and still writes the final report (exit 130).
 *
 * Usage:
 *   BASE_URL=http://127.0.0.1:8088 USERNAME=owner PASSWORD=e2e-login-pwpw \
 *   DURATION_S=60 CONCURRENCY=3 node tools/perf/load-soak.mjs
 *
 * Env: BASE_URL USERNAME PASSWORD DURATION_S WARMUP_S CONCURRENCY
 *      BFF_CONTAINER SAMPLE_INTERVAL_MS REQUEST_TIMEOUT_MS REPORT_DIR
 *
 * NOTE: numbers produced on a dev box against the e2e stack are the
 * "before" baseline of THIS machine only — they are NOT measurements of
 * the 2C/2G production target profile. See docs/reference/performance.md.
 */

import { spawn } from 'node:child_process'
import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

// ---- configuration --------------------------------------------------------

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..')
const env = (k, d) => {
  const v = process.env[k]
  return v === undefined || v === '' ? d : v
}

const CFG = {
  baseUrl: env('BASE_URL', 'http://127.0.0.1:8088').replace(/\/+$/, ''),
  username: env('USERNAME', 'owner'),
  // Fixture credential seeded by `e2e/stack/run-smoke.sh up` (E2E_LOGIN).
  // Test fixture for the hermetic local stack — never a real secret.
  password: env('PASSWORD', 'e2e-login-pwpw'),
  durationS: Number(env('DURATION_S', 300)),
  warmupS: Number(env('WARMUP_S', 60)),
  concurrency: Number(env('CONCURRENCY', 5)),
  bffContainer: env('BFF_CONTAINER', 'lumirss-e2e-bff'),
  sampleIntervalMs: Number(env('SAMPLE_INTERVAL_MS', 1000)),
  requestTimeoutMs: Number(env('REQUEST_TIMEOUT_MS', 30000)),
  reportDir: env('REPORT_DIR', join(ROOT, 'tools', 'perf', 'reports')),
  searchQuery: env('SEARCH_QUERY', 'sqlite'),
  workspaceName: env('WORKSPACE_NAME', 'soak-mixed'),
  bookmarkUrl: env('BOOKMARK_URL', 'https://fixtures/soak-item'),
}

const MIX = [ // deterministic rotation -> exact 60/20/10/10 global mix
  'list', 'list', 'list', 'list', 'list', 'list',
  'detail', 'detail',
  'search',
  'workspace',
]
const STATS_MAX_POINTS = 600 // decimation cap for the retained stats series

// ---- fixed-size latency histogram (log2 x20 buckets) ----------------------
// Bucket k covers (2^(k/20), 2^((k+1)/20)] ms (~3.5% relative width), so the
// structure is O(buckets) regardless of request count. p50/p95 are read
// from the bucket containing the quantile with linear interpolation.

const BUCKET_OFFSET = 60 // bucket -60 ~= 0.001 ms floor
const BUCKET_COUNT = 260 // up to ~2^100 ms — far beyond any timeout

class Histogram {
  constructor() {
    this.counts = new Int32Array(BUCKET_COUNT)
    this.count = 0
    this.sum = 0
    this.min = Infinity
    this.max = 0
  }
  add(ms) {
    const v = Math.max(ms, 0.001)
    let k = Math.ceil(Math.log2(v) * 20) + BUCKET_OFFSET
    if (k < 0) k = 0
    if (k >= BUCKET_COUNT) k = BUCKET_COUNT - 1
    this.counts[k] += 1
    this.count += 1
    this.sum += v
    if (v < this.min) this.min = v
    if (v > this.max) this.max = v
  }
  quantile(q) {
    if (this.count === 0) return null
    const target = Math.max(1, Math.ceil(q * this.count))
    let acc = 0
    for (let k = 0; k < BUCKET_COUNT; k++) {
      acc += this.counts[k]
      if (acc >= target) {
        const lo = Math.pow(2, (k - BUCKET_OFFSET) / 20)
        const hi = Math.pow(2, (k + 1 - BUCKET_OFFSET) / 20)
        const prev = acc - this.counts[k]
        const frac = this.counts[k] > 0 ? (target - prev) / this.counts[k] : 0
        return lo + (hi - lo) * frac
      }
    }
    return this.max
  }
  snapshot() {
    if (this.count === 0) return null
    return {
      count: this.count,
      meanMs: round(this.sum / this.count),
      minMs: round(this.min),
      maxMs: round(this.max),
      p50Ms: round(this.quantile(0.5)),
      p95Ms: round(this.quantile(0.95)),
    }
  }
}

const round = (x) => Math.round(x * 1000) / 1000

// ---- per-endpoint, per-phase aggregation ----------------------------------
// endpoints[label][phase] = { hist, errors, statuses: {code: n} }

const endpoints = new Map()
const phaseOf = (t, warmupEnd) => (t < warmupEnd ? 'warmup' : 'steady')

function record(label, phase, ms, status) {
  if (!endpoints.has(label)) {
    endpoints.set(label, {
      warmup: { hist: new Histogram(), errors: 0, statuses: {} },
      steady: { hist: new Histogram(), errors: 0, statuses: {} },
    })
  }
  const slot = endpoints.get(label)[phase]
  slot.hist.add(ms)
  if (status === null || status < 200 || status >= 300) slot.errors += 1
  const key = String(status ?? 'network')
  slot.statuses[key] = (slot.statuses[key] ?? 0) + 1
}

function endpointsSnapshot() {
  const out = {}
  for (const [label, phases] of endpoints) {
    out[label] = {}
    for (const phase of ['warmup', 'steady']) {
      const s = phases[phase].hist.snapshot()
      if (!s) continue
      out[label][phase] = {
        ...s,
        errors: phases[phase].errors,
        errorRate: s.count ? round(phases[phase].errors / s.count) : null,
        statuses: { ...phases[phase].statuses },
      }
    }
  }
  return out
}

// ---- session (login once, re-login on 401) --------------------------------

let cookie = null
let reAuths = 0
let loginPromise = null

async function login(force = false) {
  if (loginPromise && !force) return loginPromise
  loginPromise = (async () => {
    const res = await fetch(`${CFG.baseUrl}/api/v1/auth/login`, {
      method: 'POST',
      headers: { 'content-type': 'application/json', origin: CFG.baseUrl },
      body: JSON.stringify({ username: CFG.username, password: CFG.password }),
      signal: AbortSignal.timeout(CFG.requestTimeoutMs),
    })
    if (res.status !== 200 && res.status !== 204) {
      throw new Error(`login failed: HTTP ${res.status}`)
    }
    const setCookie = res.headers.get('set-cookie')
    if (!setCookie) throw new Error('login returned no session cookie')
    // A login while a session already exists is a RE-login (401 refresh);
    // the initial login is setup, not a re-auth event.
    if (cookie !== null) reAuths += 1
    cookie = setCookie.split(';')[0]
  })().finally(() => { loginPromise = null })
  return loginPromise
}

function baseHeaders() {
  // Origin: the BFF's CSRF gate requires a same-origin header on unsafe
  // methods; harmless (and realistic — the web client sends it) on GETs.
  const h = { origin: CFG.baseUrl }
  if (cookie) h.cookie = cookie
  return h
}

/** One authenticated request; on 401 re-login once and retry once.
 *  Returns { status, ms } — status is null on network error/timeout. */
async function request(method, path, { body } = {}) {
  const started = performance.now()
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      const res = await fetch(`${CFG.baseUrl}${path}`, {
        method,
        headers: {
          ...baseHeaders(),
          ...(body !== undefined ? { 'content-type': 'application/json' } : {}),
        },
        ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
        signal: AbortSignal.timeout(CFG.requestTimeoutMs),
      })
      if (res.status === 401 && attempt === 0) {
        await login(true)
        continue
      }
      // Drain the body so the socket is reused, but never parse it here.
      try { await res.arrayBuffer() } catch { /* best-effort */ }
      return { status: res.status, ms: performance.now() - started }
    } catch (err) {
      if (attempt === 1) return { status: null, ms: performance.now() - started, error: String(err) }
      // network blip: one retry after refreshing the session is cheap and
      // keeps a single 30s timeout from ending the scenario early.
      await sleep(250)
    }
  }
}

// ---- shared load state (all bounded) --------------------------------------

const entryRefs = [] // rolling window of recent entryRefs for the detail leg
const ENTRY_REF_WINDOW = 100

// ---- scenarios -------------------------------------------------------------

async function scenarioList() {
  const r = await request('GET', '/api/v1/entries')
  return { label: 'GET /api/v1/entries', r }
}

async function scenarioDetail() {
  // Detail needs an entryRef from a prior list response. The rolling
  // window is filled by scenarioList below; if the window is still empty
  // (cold start or empty stack), fall back to a list request and say so.
  const ref = entryRefs[Math.floor(Math.random() * entryRefs.length)]
  if (!ref) return { label: 'GET /api/v1/entries (detail-fallback)', r: await request('GET', '/api/v1/entries') }
  const r = await request('GET', `/api/v1/entries/${encodeURIComponent(ref)}`)
  return { label: 'GET /api/v1/entries/{entryRef}', r }
}

async function scenarioSearch() {
  const q = encodeURIComponent(CFG.searchQuery)
  const r = await request('GET', `/api/v1/search?q=${q}&limit=20`)
  return { label: 'GET /api/v1/search', r }
}

let workspaceId = null
let bookmarkItemRef = null

async function scenarioWorkspace() {
  const steps = []
  const list = await request('GET', '/api/v1/workspaces')
  steps.push({ label: 'GET /api/v1/workspaces', r: list })
  if (workspaceId && bookmarkItemRef) {
    const added = await request('POST', `/api/v1/workspaces/${workspaceId}/items`, {
      body: { itemRef: bookmarkItemRef },
    })
    steps.push({ label: 'POST /api/v1/workspaces/{id}/items', r: added })
    const removed = await request(
      'DELETE',
      `/api/v1/workspaces/${workspaceId}/items/${encodeURIComponent(bookmarkItemRef)}`,
    )
    steps.push({ label: 'DELETE /api/v1/workspaces/{id}/items/{ref}', r: removed })
  }
  return steps
}

// ---- setup (unmeasured): login, workspace, bookmark, list prime ------------

async function setup() {
  await login()

  // find-or-create the soak workspace (rerun-tolerant, like the smoke)
  const created = await fetch(`${CFG.baseUrl}/api/v1/workspaces`, {
    method: 'POST',
    headers: { ...baseHeaders(), 'content-type': 'application/json' },
    body: JSON.stringify({ name: CFG.workspaceName }),
    signal: AbortSignal.timeout(CFG.requestTimeoutMs),
  })
  try { await created.arrayBuffer() } catch { /* ignore */ }

  const wsRes = await fetch(`${CFG.baseUrl}/api/v1/workspaces`, {
    headers: baseHeaders(), signal: AbortSignal.timeout(CFG.requestTimeoutMs),
  })
  const wsBody = await wsRes.json()
  const ws = (wsBody.items ?? []).find((w) => w.name === CFG.workspaceName)
  if (!ws) throw new Error(`workspace '${CFG.workspaceName}' missing after find-or-create`)
  workspaceId = ws.id

  // idempotent-on-url bookmark; its ref is the workspace add/remove payload
  const bmRes = await fetch(`${CFG.baseUrl}/api/v1/library/bookmarks`, {
    method: 'POST',
    headers: { ...baseHeaders(), 'content-type': 'application/json' },
    body: JSON.stringify({ url: CFG.bookmarkUrl, title: 'soak item' }),
    signal: AbortSignal.timeout(CFG.requestTimeoutMs),
  })
  if (bmRes.status !== 201) throw new Error(`bookmark setup failed: HTTP ${bmRes.status}`)
  const bm = await bmRes.json()
  bookmarkItemRef = bm.ref

  // prime the detail window with one unmeasured list call
  const listRes = await fetch(`${CFG.baseUrl}/api/v1/entries`, {
    headers: baseHeaders(), signal: AbortSignal.timeout(CFG.requestTimeoutMs),
  })
  if (listRes.status === 200) {
    const body = await listRes.json()
    for (const item of body.items ?? []) {
      if (item.entryRef && entryRefs.length < ENTRY_REF_WINDOW) entryRefs.push(item.entryRef)
    }
  }
}

// ---- load workers ----------------------------------------------------------

let stop = false
let mixCursor = 0

async function workerLoop(deadline, warmupEnd) {
  while (!stop) {
    const t = performance.now()
    if (t >= deadline) break
    const phase = phaseOf(t, warmupEnd)
    const scenario = MIX[mixCursor++ % MIX.length]
    if (scenario === 'list') {
      const { label, r } = await scenarioList()
      record(label, phase, r.ms, r.status)
      // The detail leg's ref window is filled by the separate bounded
      // refRefresher tick, so the measured list leg stays parse-free.
    } else if (scenario === 'detail') {
      const { label, r } = await scenarioDetail()
      record(label, phase, r.ms, r.status)
    } else if (scenario === 'search') {
      const { label, r } = await scenarioSearch()
      record(label, phase, r.ms, r.status)
    } else {
      for (const { label, r } of await scenarioWorkspace()) {
        record(label, phase, r.ms, r.status)
      }
    }
  }
}

/** Fill the rolling entryRef window from list responses.
 *  Runs alongside the workers on a 5s tick, bounded parse, no growth. */
async function refRefresher(deadline) {
  while (!stop && performance.now() < deadline) {
    await sleep(5000)
    if (stop || performance.now() >= deadline) break
    try {
      const res = await fetch(`${CFG.baseUrl}/api/v1/entries`, {
        headers: baseHeaders(), signal: AbortSignal.timeout(CFG.requestTimeoutMs),
      })
      if (res.status !== 200) continue
      const body = await res.json()
      for (const item of body.items ?? []) {
        if (!item.entryRef) continue
        if (entryRefs.length >= ENTRY_REF_WINDOW) entryRefs.shift()
        entryRefs.push(item.entryRef)
      }
    } catch { /* best-effort; detail leg falls back to list */ }
  }
}

// ---- container stats sampling (best-effort) --------------------------------

const stats = {
  available: null, // null = unknown until first sample attempt
  firstError: null,
  sampleErrors: 0,
  phases: {
    warmup: { samples: 0, cpuSum: 0, cpuMax: 0, memSum: 0, memMin: Infinity, memMax: 0 },
    steady: { samples: 0, cpuSum: 0, cpuMax: 0, memSum: 0, memMin: Infinity, memMax: 0 },
  },
  series: [], // decimated in place, never exceeds STATS_MAX_POINTS
  seriesStride: 1,
}

const parseBytes = (s) => {
  const m = /([\d.]+)\s*(B|KiB|MiB|GiB|TiB)/.exec(s)
  if (!m) return NaN
  const mult = { B: 1, KiB: 1024, MiB: 1024 ** 2, GiB: 1024 ** 3, TiB: 1024 ** 4 }[m[2]]
  return Number(m[1]) * mult
}
const parsePct = (s) => {
  const m = /([\d.]+)%/.exec(s)
  return m ? Number(m[1]) : NaN
}

function dockerStatsOnce() {
  return new Promise((resolve) => {
    const child = spawn(
      'docker',
      ['stats', '--no-stream', '--format', '{{.CPUPerc}}\t{{.MemUsage}}', CFG.bffContainer],
      { stdio: ['ignore', 'pipe', 'pipe'] },
    )
    let out = ''
    const timer = setTimeout(() => { child.kill('SIGKILL') }, CFG.sampleIntervalMs * 4)
    child.stdout.on('data', (d) => { out += d })
    child.on('error', (err) => { clearTimeout(timer); resolve({ error: err }) })
    child.on('close', (code) => {
      clearTimeout(timer)
      if (code !== 0) return resolve({ error: new Error(`docker stats exited ${code}`) })
      const [cpu, mem] = out.trim().split('\t')
      resolve({ cpuPct: parsePct(cpu ?? ''), memBytes: parseBytes((mem ?? '').split('/')[0] ?? '') })
    })
  })
}

function recordStats(phase, cpuPct, memBytes) {
  const p = stats.phases[phase]
  p.samples += 1
  p.cpuSum += cpuPct
  if (cpuPct > p.cpuMax) p.cpuMax = cpuPct
  p.memSum += memBytes
  if (memBytes < p.memMin) p.memMin = memBytes
  if (memBytes > p.memMax) p.memMax = memBytes
  // bounded series: decimate in place (drop every other retained point)
  // whenever the cap would overflow, doubling the stride instead.
  stats.series.push({ t: Math.round(performance.now()), cpuPct, memBytes })
  if (stats.series.length > STATS_MAX_POINTS) {
    stats.series = stats.series.filter((_, i) => i % 2 === 0)
    stats.seriesStride *= 2
  }
}

async function statsLoop(warmupEnd, deadline) {
  while (!stop && performance.now() < deadline) {
    const started = performance.now()
    const r = await dockerStatsOnce()
    if (r.error) {
      stats.sampleErrors += 1
      if (stats.available === null) stats.available = false
      if (!stats.firstError) stats.firstError = String(r.error)
    } else if (Number.isFinite(r.cpuPct) && Number.isFinite(r.memBytes)) {
      if (stats.available === null) stats.available = true
      recordStats(phaseOf(started, warmupEnd), r.cpuPct, r.memBytes)
    } else {
      stats.sampleErrors += 1
    }
    const elapsed = performance.now() - started
    await sleep(Math.max(0, CFG.sampleIntervalMs - elapsed))
  }
}

function statsSnapshot(phase) {
  const p = stats.phases[phase]
  if (p.samples === 0) return null
  return {
    samples: p.samples,
    cpuPct: { avg: round(p.cpuSum / p.samples), max: round(p.cpuMax) },
    memBytes: {
      min: Math.round(p.memMin),
      avg: Math.round(p.memSum / p.samples),
      max: Math.round(p.memMax),
    },
  }
}

// ---- reporting -------------------------------------------------------------

const humanBytes = (b) => {
  if (!Number.isFinite(b)) return 'n/a'
  const units = ['B', 'KiB', 'MiB', 'GiB']
  let i = 0
  let v = b
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++ }
  return `${round(v)}${units[i]}`
}

function printSummary(report) {
  const steady = report.endpoints
  console.log('\n=== soak summary (steady phase) ===')
  console.log(`base: ${report.meta.baseUrl}  concurrency: ${report.meta.concurrency}  steady: ${report.meta.durationS}s  warmup: ${report.meta.warmupS}s`)
  for (const [label, phases] of Object.entries(steady)) {
    const s = phases.steady
    if (!s) continue
    console.log(
      `${label.padEnd(44)} n=${String(s.count).padStart(6)}  p50=${String(s.p50Ms).padStart(8)}ms  p95=${String(s.p95Ms).padStart(8)}ms  err=${s.errors}`,
    )
  }
  const res = report.resources?.steady
  if (res) {
    console.log(
      `bff container (steady): cpu avg ${res.cpuPct.avg}% / max ${res.cpuPct.max}%  mem min ${humanBytes(res.memBytes.min)} / avg ${humanBytes(res.memBytes.avg)} / max ${humanBytes(res.memBytes.max)}`,
    )
  }
  if (report.resources && report.resources.statsAvailable === false) {
    console.log(`bff container stats: UNAVAILABLE (${report.resources.statsFirstError ?? 'unknown'}) — HTTP metrics only`)
  }
  console.log(`report: ${report.meta.reportPath}`)
}

async function main() {
  for (const [k, v] of Object.entries(CFG)) {
    if (typeof v === 'number' && (!Number.isFinite(v) || v <= 0)) {
      console.error(`config error: ${k} must be a positive number (got ${v})`)
      process.exit(2)
    }
  }

  let interrupted = false
  const onSigint = () => {
    if (interrupted) process.exit(130)
    interrupted = true
    stop = true
    console.error('\nSIGINT: stopping workers, writing final report…')
  }
  process.on('SIGINT', onSigint)

  console.error(`load-soak: ${CFG.baseUrl} user=${CFG.username} warmup=${CFG.warmupS}s steady=${CFG.durationS}s concurrency=${CFG.concurrency}`)

  try {
    await setup()
  } catch (err) {
    console.error(`setup failed: ${err.message ?? err}`)
    console.error('is the e2e stack up?  docker compose -f e2e/stack/docker-compose.e2e.yml up -d --build && e2e/stack/run-smoke.sh up')
    process.exit(2)
  }
  console.error(`setup ok: workspace=${CFG.workspaceName} entryRefs=${entryRefs.length}`)

  const startedAt = new Date().toISOString()
  const t0 = performance.now()
  const warmupEnd = t0 + CFG.warmupS * 1000
  const deadline = warmupEnd + CFG.durationS * 1000

  const jobs = []
  for (let i = 0; i < CFG.concurrency; i++) jobs.push(workerLoop(deadline, warmupEnd))
  jobs.push(statsLoop(warmupEnd, deadline))
  jobs.push(refRefresher(deadline))
  await Promise.all(jobs)

  const finishedAt = new Date().toISOString()
  mkdirSync(CFG.reportDir, { recursive: true })
  const reportPath = join(CFG.reportDir, `soak-${Date.now()}.json`)
  const endpointStats = endpointsSnapshot()
  const sumSteady = Object.values(endpointStats).reduce((acc, e) => acc + (e.steady?.count ?? 0), 0)
  const sumAll = Object.values(endpointStats).reduce((acc, e) => acc + (e.steady?.count ?? 0) + (e.warmup?.count ?? 0), 0)
  const report = {
    meta: {
      tool: 'tools/perf/load-soak.mjs',
      startedAt,
      finishedAt,
      interrupted,
      baseUrl: CFG.baseUrl,
      username: CFG.username,
      warmupS: CFG.warmupS,
      durationS: CFG.durationS,
      concurrency: CFG.concurrency,
      scenarioMix: { listEntries: 0.6, entryDetail: 0.2, search: 0.1, workspaceAddRemove: 0.1 },
      searchQuery: CFG.searchQuery,
      bffContainer: CFG.bffContainer,
      reAuths,
      environment: 'dev-e2e-stack',
      note: 'Dev-box baseline against the e2e stack — NOT a measurement of the 2C/2G production target profile. Latency is client-observed (driver -> web/Caddy -> BFF); see docs/reference/performance.md.',
      reportPath,
    },
    totals: {
      requests: sumAll,
      steadyRequests: sumSteady,
      steadyRps: round(sumSteady / CFG.durationS),
      reAuths,
    },
    endpoints: endpointStats,
    resources: {
      statsAvailable: stats.available,
      statsFirstError: stats.firstError,
      statsSampleErrors: stats.sampleErrors,
      sampleIntervalMs: CFG.sampleIntervalMs,
      seriesStride: stats.seriesStride,
      warmup: statsSnapshot('warmup'),
      steady: statsSnapshot('steady'),
      series: stats.series,
    },
  }
  writeFileSync(reportPath, `${JSON.stringify(report, null, 2)}\n`)
  printSummary(report)
  process.exit(interrupted ? 130 : 0)
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

main().catch((err) => {
  console.error(`fatal: ${err?.stack ?? err}`)
  process.exit(1)
})
