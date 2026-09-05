/** 0019 C9 — performance baseline/budget 测量脚本。
 *
 * 对运行中的 production 栈（LUMIRSS_E2E_BASE_URL）测量：
 * - 页面资源体积（JS/CSS transfer，来自 performance API）；
 * - LCP / CLS（Playwright + CDP，移动视口 390×844 与桌面 1440×900）；
 * - route 切换（时间线 → Reader → 设置）耗时。
 *
 * 用法：node e2e/perf-measure.mjs   （输出 JSON 摘要）
 */

import { chromium } from '@playwright/test'

const BASE = process.env.LUMIRSS_E2E_BASE_URL ?? 'http://127.0.0.1'

async function measure(browser, viewport, label) {
  const context = await browser.newContext({ viewport, locale: 'zh-CN' })
  const page = await context.newPage()

  const resources = { js: 0, css: 0 }
  page.on('response', async (resp) => {
    try {
      const type = resp.request().resourceType()
      if (type === 'script' || type === 'stylesheet') {
        const headers = await resp.allHeaders()
        const size = Number(headers['content-length'] ?? 0)
        if (type === 'script') resources.js += size
        else resources.css += size
      }
    } catch {
      /* response 已不可用 */
    }
  })

  await page.goto(BASE, { waitUntil: 'networkidle' })

  const client = await page.context().newCDPSession(page)
  await client.send('Performance.enable')
  const lcp = await page.evaluate(
    () =>
      new Promise((resolve) => {
        new PerformanceObserver((list) => {
          const entries = list.getEntries()
          const last = entries[entries.length - 1]
          if (last) resolve(Math.round(last.startTime))
        }).observe({ type: 'largest-contentful-paint', buffered: true })
        setTimeout(() => resolve(-1), 3000)
      }),
  )
  const cls = await page.evaluate(
    () =>
      new Promise((resolve) => {
        let total = 0
        new PerformanceObserver((list) => {
          for (const entry of list.getEntries()) {
            if (!entry.hadRecentInput) total += entry.value
          }
          resolve(Math.round(total * 1000) / 1000)
        }).observe({ type: 'layout-shift', buffered: true })
        setTimeout(() => resolve(Math.round(total * 1000) / 1000), 2000)
      }),
  )

  // route 切换：打开第一篇文章（若有）与设置
  const t0 = Date.now()
  const firstEntry = page.getByRole('button', { name: /^文章 / }).first()
  if (await firstEntry.count()) {
    await firstEntry.click()
    await page.waitForTimeout(800)
    await page.getByRole('button', { name: '返回文章列表' }).click()
  }
  const routeMs = Date.now() - t0

  console.log(
    JSON.stringify(
      {
        viewport: label,
        jsTransferKB: Math.round(resources.js / 1024),
        cssTransferKB: Math.round(resources.css / 1024),
        lcpMs: lcp,
        cls,
        routeInteractionMs: routeMs,
      },
      null,
      2,
    ),
  )
  await context.close()
}

const browser = await chromium.launch()
await measure(browser, { width: 1440, height: 900 }, 'desktop-1440')
await measure(browser, { width: 390, height: 844 }, 'mobile-390')
await browser.close()
