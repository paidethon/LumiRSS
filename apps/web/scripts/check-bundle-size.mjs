/** Bundle guard — Phase K 防回归（build 后自动执行）。
 *
 * 读取 dist/index.html 实际引用的首屏资源（entry script + modulepreload
 * + CSS），执行两条契约：
 * 1. 首屏 JS（原始/gzip）不超上限 —— 上限基于 2026-09 分割后的实测
 *    （~643 kB raw / ~197 kB gzip）+ ~15% 余量；
 * 2. 懒加载契约：SettingsModal / MobileSettingsScreen / 一级移动页
 *    chunk 不得出现在 index.html 引用里（回归 = 有人把懒入口改回
 *    静态 import）。
 * gzip 用 zlib 同步估算（与 vite 报告一致的数量级即可）。
 */

import { readFileSync, readdirSync, statSync } from 'node:fs'
import { gzipSync } from 'node:zlib'
import { join } from 'node:path'

const dist = join(process.cwd(), 'dist')
const html = readFileSync(join(dist, 'index.html'), 'utf8')

const referenced = [...html.matchAll(/(?:src|href)="(\/assets\/[^"]+)"/g)].map((m) => m[1])
const jsAssets = referenced.filter((a) => a.endsWith('.js'))
const lazyChunks = readdirSync(join(dist, 'assets')).filter((n) => /\.js$/.test(n))

let rawTotal = 0
let gzipTotal = 0
for (const asset of jsAssets) {
  const buf = readFileSync(join(dist, asset.slice(1)))
  rawTotal += buf.length
  gzipTotal += gzipSync(buf).length
}

const RAW_LIMIT = 780 * 1024
const GZIP_LIMIT = 235 * 1024
const failures = []
if (rawTotal > RAW_LIMIT) {
  failures.push(`initial JS raw ${(rawTotal / 1024).toFixed(0)} kB > ${(RAW_LIMIT / 1024).toFixed(0)} kB`)
}
if (gzipTotal > GZIP_LIMIT) {
  failures.push(`initial JS gzip ${(gzipTotal / 1024).toFixed(0)} kB > ${(GZIP_LIMIT / 1024).toFixed(0)} kB`)
}

// 懒加载契约：这些模块名若出现在 index.html，说明懒入口被改回静态。
const LAZY_PREFIXES = ['SettingsModal', 'MobileSettingsScreen', 'SettingItem', 'FavoritesPage', 'SearchPage', 'SubscriptionsPage']
for (const name of LAZY_PREFIXES) {
  if (lazyChunks.some((n) => n.startsWith(name)) && referenced.some((r) => r.includes(name))) {
    failures.push(`${name} chunk is referenced by index.html — must stay lazy-loaded`)
  }
}

if (failures.length > 0) {
  console.error(`bundle guard FAILED:\n  - ${failures.join('\n  - ')}`)
  process.exit(1)
}
console.log(
  `bundle guard OK: initial JS ${(rawTotal / 1024).toFixed(0)} kB raw / ${(gzipTotal / 1024).toFixed(0)} kB gzip (${jsAssets.length} chunks); lazy settings/page chunks unreferenced`,
)
