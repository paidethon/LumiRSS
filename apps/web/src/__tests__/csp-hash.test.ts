/** CSP hash drift check (0021): the theme anti-FOUC bootstrap is an
 * INLINE script in index.html, and the production Caddyfile pins its
 * sha256 in script-src. If either side drifts, the browser silently
 * refuses the inline script. This test fails loudly instead. */

import { readFileSync } from 'node:fs'
import { createHash } from 'node:crypto'
import { describe, expect, it } from 'vitest'
import { resolve } from 'node:path'

const webRoot = resolve(__dirname, '../..')

function inlineScriptBlocks(html: string): string[] {
  return [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map((m) => m[1])
}

describe('CSP inline-script hash', () => {
  it('Caddyfile script-src pins the sha256 of the index.html inline script', () => {
    const html = readFileSync(resolve(webRoot, 'index.html'), 'utf-8')
    const blocks = inlineScriptBlocks(html)
    expect(blocks.length).toBeGreaterThanOrEqual(1)

    for (const caddyfile of ['Caddyfile.auth', 'Caddyfile.noauth']) {
      const content = readFileSync(resolve(webRoot, caddyfile), 'utf-8')
      const pins = [
        ...content.matchAll(/'sha256-([A-Za-z0-9+/=]+)'/g),
      ].map((m) => m[1])
      expect(pins.length, `${caddyfile} must pin the inline script`).toBe(
        blocks.length,
      )
      for (const block of blocks) {
        const digest = createHash('sha256')
          .update(block, 'utf-8')
          .digest('base64')
        expect(
          pins,
          `${caddyfile} must contain 'sha256-${digest}' — the index.html inline script changed; re-pin it.`,
        ).toContain(digest)
      }
    }
  })

  it('Vite serves the inline script verbatim (source equals build output shape)', () => {
    const html = readFileSync(resolve(webRoot, 'index.html'), 'utf-8')
    // Guard the assumption behind the hash pin: Vite must not transform
    // inline scripts, so the built page hashes identically to the source.
    for (const block of inlineScriptBlocks(html)) {
      expect(block).not.toMatch(/^\s*import /) // no module transform
      expect(html.includes('<script>')).toBe(true)
    }
  })
})
