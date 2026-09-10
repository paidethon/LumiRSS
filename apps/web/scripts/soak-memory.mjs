/** Browser memory soak — Phase L（手动/发布前运行，不进 CI）。
 *
 * 自包含：一个 Node http 服务器同时伺服 dist/ 静态文件与内存态 mock
 * BFF API（feeds / 分页 entries / 详情 / 搜索 / 状态写入 / auth 探测），
 * 然后 Playwright Chromium 按阶段驱动真实 UI：
 *
 *   M0  冷启动（首屏）
 *   M1  连续打开 100 篇文章（detail 加载 + 返回）
 *   M2  搜索 50 次（每次新 query = 新缓存 key）
 *   M3  打开/关闭设置 30 次（懒加载 chunk 复用 + Dialog 挂卸载）
 *   M4  收藏/取消 25 次（mutation + 精确缓存补丁）
 *   M5  列表滚动（加载多页）
 *   M6  静置 60s 后
 *
 * 每阶段记录 CDP Performance.getMetrics（JSHeapUsedSize / DOMNodes /
 * JSEventListeners），阶段间强制 GC 仅用于诊断（帮助区分「增长中的
 * 可回收垃圾」与「泄漏」）。判定标准（非硬性断言，输出供人审）：
 * warm-up 后 heap 应趋于平台期；逐阶段线性增长（如每轮 +5MB 持续）
 * 才视为泄漏。
 *
 * 用法：
 *   node scripts/soak-memory.mjs            # 完整 soak（~8–10 分钟）
 *   node scripts/soak-memory.mjs --quick    # 冒烟版（计数缩至 ~1/5）
 *   node scripts/soak-memory.mjs --mobile   # 只跑 390×844（默认双视口）
 *
 * 前置：pnpm build（脚本伺服 dist/）。
 */

import http from 'node:http'
import { createReadStream, existsSync, readFileSync } from 'node:fs'
import { extname, join } from 'node:path'
import { chromium } from '@playwright/test'

const PORT = Number(process.env.SOAK_PORT ?? 18190)
const DIST = join(import.meta.dirname, '..', 'dist')

const quick = process.argv.includes('--quick')
const desktopOnly = process.argv.includes('--desktop')
const mobileOnly = process.argv.includes('--mobile')
const N = quick
  ? { articles: 20, searches: 10, settings: 6, stars: 5, settleMs: 15_000 }
  : { articles: 100, searches: 50, settings: 30, stars: 25, settleMs: 60_000 }

// ---- mock 数据（确定性生成，无真实内容） ----

const FEED = { feedUrl: 'https://soak.example/feed.xml', title: 'Soak 源', categoryLabel: null, unreadCount: 0, id: 't/1' }
const PAGE_SIZE = 20

function listItem(i) {
  return {
    entryRef: `s${i}.soak`,
    title: `Soak 文章 ${i} — 用于内存浸泡的确定性标题`,
    feedTitle: FEED.title,
    author: null,
    url: `https://soak.example/${i}`,
    publishedAt: new Date(Date.UTC(2026, 8, 1, 8, i % 60)).toISOString(),
    read: i % 3 === 0,
    starred: i % 7 === 0,
  }
}

function detail(i) {
  const body = Array.from(
    { length: 24 },
    (_, p) =>
      `<p>第 ${p} 段：这是文章 ${i} 的正文内容，长度接近真实资讯文章，包含中英文混排 vocabulary 与一些 numbers 12345。</p>`,
  ).join('\n')
  return { ...listItem(i), contentText: `文章 ${i} 正文`, contentHtml: `<div>${body}</div>` }
}

function json(res, body, status = 200) {
  res.writeHead(status, {
    'content-type': 'application/json',
    'cache-control': 'no-store',
  })
  res.end(JSON.stringify(body))
}

// ---- 一体化服务器：静态 dist + mock API ----

const server = http.createServer((req, res) => {
  const url = new URL(req.url, `http://127.0.0.1:${PORT}`)
  const path = url.pathname

  if (path === '/api/v1/auth/session') return json(res, { authenticated: true, mode: 'basic' })
  if (path === '/api/v1/version') return json(res, { version: 'soak', commit: '', apiVersion: 1 })
  if (path === '/api/v1/feeds') return json(res, [FEED])
  if (path === '/api/v1/entries') {
    const cursor = url.searchParams.get('cursor')
    const from = cursor === null ? 0 : Number(cursor.split(':')[1] ?? 0) || 0
    const items = Array.from({ length: PAGE_SIZE }, (_, i) => listItem(from + i))
    const next = from + PAGE_SIZE < 600 ? `c:${from + PAGE_SIZE}` : null
    return json(res, { items, nextCursor: next })
  }
  if (path === '/api/v1/search') {
    const items = Array.from({ length: PAGE_SIZE }, (_, i) => ({
      ...listItem(i),
      snippet: '搜索命中片段，确定性文本。',
    }))
    return json(res, { items, nextCursor: null })
  }
  const detailMatch = path.match(/^\/api\/v1\/entries\/(s\d+)\.soak\/?state?$/)
  if (detailMatch && path.endsWith('/state')) {
    return json(res, { ok: true }, 204)
  }
  const entryMatch = path.match(/^\/api\/v1\/entries\/s(\d+)\.soak$/)
  if (entryMatch) return json(res, detail(Number(entryMatch[1])))

  // 静态文件（dist + public 遗留）；sw.js 故意 404——soak 测的是应用
  // 内存，不混入 Service Worker 缓存变量。
  let file = path === '/' ? '/index.html' : path
  if (file.startsWith('/assets/') || file === '/index.html' || file.startsWith('/icons/')) {
    const full = join(DIST, file)
    if (existsSync(full)) {
      const types = { '.js': 'text/javascript', '.css': 'text/css', '.html': 'text/html', '.png': 'image/png', '.svg': 'image/svg+xml', '.webmanifest': 'application/manifest+json' }
      res.writeHead(200, { 'content-type': types[extname(full)] ?? 'application/octet-stream' })
      createReadStream(full).pipe(res)
      return
    }
  }
  res.writeHead(404).end()
})

// ---- 测量 ----

async function metrics(client, page) {
  await client.send('HeapProfiler.collectGarbage')
  await new Promise((r) => setTimeout(r, 400))
  const { metrics: m } = await client.send('Performance.getMetrics')
  const pick = (name) => m.find((x) => x.name === name)?.value ?? 0
  return {
    heapMB: +(pick('JSHeapUsedSize') / 1048576).toFixed(1),
    domNodes: pick('Nodes'),
    listeners: pick('JSEventListeners'),
    documents: pick('Documents'),
    url: page.url().slice(-40),
  }
}

async function runViewport(browser, viewport, label) {
  const context = await browser.newContext({ viewport, locale: 'zh-CN' })
  const page = await context.newPage()
  const client = await context.newCDPSession(page)
  await client.send('Performance.enable')
  const trace = []

  const mark = async (phase) => {
    trace.push({ phase, ...(await metrics(client, page)) })
    console.error(`  [${label}] ${phase}: heap=${trace.at(-1).heapMB}MB nodes=${trace.at(-1).domNodes} listeners=${trace.at(-1).listeners}`)
  }

  await page.goto(`http://127.0.0.1:${PORT}/`, { waitUntil: 'networkidle' })
  await mark('M0 冷启动')

  /** 点掉一行/卡片的可见实例（桌面 EntryRow 与移动 EntryCard 双挂载，
   * CSS 各隐藏其一——必须点真正可见的那个）。 */
  async function clickVisibleRow(i) {
    const matches = page.locator('[data-entry-ref]').filter({ hasText: `Soak 文章 ${i} ` })
    const count = await matches.count()
    for (let k = 0; k < count; k++) {
      const candidate = matches.nth(k)
      if (await candidate.isVisible().catch(() => false)) {
        await candidate.click()
        return true
      }
    }
    return false
  }

  // M1 连续打开文章（移动端点卡片 / 桌面点行；Escape 返回）
  for (let i = 0; i < N.articles; i++) {
    if (!(await clickVisibleRow(i))) break
    await page.waitForTimeout(60)
    await page.keyboard.press('Escape')
  }
  await mark(`M1 打开 ${N.articles} 篇文章`)

  // M2 搜索 N 次（每次新 query）
  await page.getByRole('button', { name: '搜索' }).first().click()
  const searchBox = page.getByRole('searchbox').or(page.getByRole('textbox', { name: /搜索/ })).first()
  for (let i = 0; i < N.searches; i++) {
    await searchBox.fill(`查询词 ${i}`)
    await page.waitForTimeout(150)
  }
  await mark(`M2 搜索 ${N.searches} 次`)

  // M3 设置开关（首访加载 chunk，之后纯挂卸载）。移动端入口在导航
  // 抽屉里：先「打开导航」再「打开设置」；桌面侧栏直连。
  const navButton = page.getByRole('button', { name: '打开导航' }).first()
  const settingsViaDrawer = !(await page.getByRole('button', { name: '打开设置' }).first().isVisible().catch(() => false))
  for (let i = 0; i < N.settings; i++) {
    if (settingsViaDrawer) await navButton.click()
    await page.getByRole('button', { name: '打开设置' }).first().click()
    await page.waitForTimeout(i === 0 ? 800 : 120)
    await page.getByRole('button', { name: '关闭设置' }).first().click()
    await page.waitForTimeout(80)
    if (settingsViaDrawer) await page.keyboard.press('Escape')
  }
  await mark(`M3 设置开关 ${N.settings} 次`)

  // M4 收藏/取消（mutation + 精确补丁）。返回首页：移动端点底栏 tab，
  // 桌面端列表常驻（无 tab bar，无需导航）。
  const homeTab = page.getByRole('button', { name: '首页' }).first()
  if (await homeTab.isVisible().catch(() => false)) await homeTab.click()
  for (let i = 0; i < N.stars; i++) {
    if (!(await clickVisibleRow(i))) break
    const star = page.getByRole('button', { name: /收藏|取消收藏/ }).first()
    await star.click()
    await page.waitForTimeout(60)
    await page.keyboard.press('Escape')
  }
  await mark(`M4 收藏切换 ${N.stars} 次`)

  // M5 列表滚动（加载多页）
  const scroller = page.locator('main section.overflow-y-auto, main div.overflow-y-auto').first()
  for (let i = 0; i < (quick ? 6 : 25); i++) {
    await scroller.evaluate((el) => el.scrollTo({ top: el.scrollHeight }))
    await page.waitForTimeout(200)
  }
  await mark('M5 列表滚动多页')

  // M6 静置
  await page.waitForTimeout(N.settleMs)
  await mark('M6 静置后')

  await context.close()
  return { viewport: label, trace }
}

// ---- main ----

await new Promise((resolve) => server.listen(PORT, '127.0.0.1', resolve))
console.error(`soak server on http://127.0.0.1:${PORT} (dist=${DIST})`)

const browser = await chromium.launch()
const results = []
if (!mobileOnly) {
  results.push(await runViewport(browser, { width: 1440, height: 900 }, 'desktop-1440'))
}
if (!desktopOnly) {
  results.push(await runViewport(browser, { width: 390, height: 844 }, 'mobile-390'))
}
await browser.close()
server.close()

// 平台期摘要：M1→M6 的 heap 斜率（MB/阶段）与 DOM 增量
for (const { viewport, trace } of results) {
  const m1 = trace.find((t) => t.phase.startsWith('M1'))
  const m6 = trace.at(-1)
  const slope = m1 && m6 ? +((m6.heapMB - m1.heapMB) / 5).toFixed(2) : null
  console.error(`  [${viewport}] M1→M6 heap 斜率 ≈ ${slope} MB/阶段`)
}

console.log(JSON.stringify({ quick, counts: N, results }, null, 2))
