import { readFileSync } from 'node:fs'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

import { describe, expect, it } from 'vitest'

/** 0007 Test H — PWA 自动验证（纯 Node，零依赖，不新建 schema library）：
 * manifest 必需字段 + index.html metadata + PNG 真实格式与尺寸
 * （直接解析 PNG 魔数与 IHDR，不以文件名猜测）。 */

const webRoot = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const publicDir = resolve(webRoot, 'public')

const manifest = JSON.parse(
  readFileSync(resolve(publicDir, 'manifest.webmanifest'), 'utf8'),
) as {
  name?: unknown
  short_name?: unknown
  start_url?: unknown
  scope?: unknown
  display?: unknown
  icons?: { src?: string; sizes?: string; type?: string; purpose?: string }[]
}

const indexHtml = readFileSync(resolve(webRoot, 'index.html'), 'utf8')

/** 解析 PNG：校验 8 字节魔数 + IHDR 宽高（offset 16 起，大端）。 */
function pngSize(file: string): { width: number; height: number } {
  const buf = readFileSync(resolve(publicDir, file))
  const signature = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])
  expect(buf.subarray(0, 8).equals(signature), `${file}: 不是合法 PNG（魔数不符）`).toBe(true)
  expect(buf.toString('ascii', 12, 16)).toBe('IHDR')
  return { width: buf.readUInt32BE(16), height: buf.readUInt32BE(20) }
}

describe('Test H — manifest.webmanifest', () => {
  it('包含 name / short_name / start_url / scope', () => {
    expect(manifest.name).toBe('LumiRSS')
    expect(manifest.short_name).toBe('LumiRSS')
    expect(manifest.start_url).toBe('/')
    expect(manifest.scope).toBe('/')
  })

  it('display 为 standalone', () => {
    expect(manifest.display).toBe('standalone')
  })

  it('icons 包含 192×192 与 512×512 PNG', () => {
    const icons = manifest.icons ?? []
    expect(
      icons.some((i) => i.sizes === '192x192' && i.type === 'image/png'),
    ).toBe(true)
    expect(
      icons.some((i) => i.sizes === '512x512' && i.type === 'image/png'),
    ).toBe(true)
  })

  it('存在 maskable icon 声明', () => {
    expect(
      (manifest.icons ?? []).some((i) => i.purpose === 'maskable'),
    ).toBe(true)
  })

  it('manifest 只含静态公开 metadata（不含 secret / 上游地址）', () => {
    const raw = JSON.stringify(manifest)
    expect(raw).not.toMatch(/FRESHRSS|password|token|Authorization|api[-_]?key/i)
    expect(raw).not.toContain('8080') // FreshRSS 端口
  })
})

describe('index.html PWA metadata', () => {
  it('包含 manifest link / theme-color / apple-touch-icon', () => {
    expect(indexHtml).toContain('<link rel="manifest" href="/manifest.webmanifest" />')
    expect(indexHtml).toContain('<meta name="theme-color" content="#ffffff" />')
    expect(indexHtml).toContain('<link rel="apple-touch-icon" href="/icons/apple-touch-icon.png" />')
  })

  it('viewport 含 viewport-fit=cover 且 meta viewport 只出现一次', () => {
    const viewports = indexHtml.match(/<meta\s+name="viewport"/g) ?? []
    expect(viewports).toHaveLength(1)
    expect(indexHtml).toContain('viewport-fit=cover')
    expect(indexHtml).toContain('width=device-width')
    expect(indexHtml).toContain('initial-scale=1')
  })
})

describe('PNG icon 真实尺寸（IHDR 解析，不以文件名猜测）', () => {
  it('icon-192.png 为 192×192', () => {
    expect(pngSize('icons/icon-192.png')).toEqual({ width: 192, height: 192 })
  })

  it('icon-512.png 为 512×512', () => {
    expect(pngSize('icons/icon-512.png')).toEqual({ width: 512, height: 512 })
  })

  it('icon-maskable-512.png 为 512×512', () => {
    expect(pngSize('icons/icon-maskable-512.png')).toEqual({ width: 512, height: 512 })
  })

  it('apple-touch-icon.png 为 180×180', () => {
    expect(pngSize('icons/apple-touch-icon.png')).toEqual({ width: 180, height: 180 })
  })
})
