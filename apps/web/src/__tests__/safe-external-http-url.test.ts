import { describe, expect, it } from 'vitest'
import { safeExternalHttpUrl } from '../lib/safe-external-http-url'

describe('safeExternalHttpUrl — 「打开原文」URL 安全边界', () => {
  it('绝对 https / http → 放行', () => {
    expect(safeExternalHttpUrl('https://example.com/article')).toBe(
      'https://example.com/article',
    )
    expect(safeExternalHttpUrl('http://example.com/a?b=1#c')).toBe(
      'http://example.com/a?b=1#c',
    )
  })

  it.each([
    'javascript:alert(1)',
    'JAVASCRIPT:alert(1)', // 协议大小写不敏感
    'data:text/html,<script>alert(1)</script>',
    'file:///etc/passwd',
    'ftp://example.com/file',
    'mailto:someone@example.com',
  ])('危险/非 http 协议 %s → null', (value) => {
    expect(safeExternalHttpUrl(value)).toBeNull()
  })

  it.each([
    '/relative/path',
    'article.html',
    '../escape',
    '//protocol-relative.example/x', // 无协议 → 不可解析为绝对 http/https
  ])('相对 URL %s → null（不用当前 origin 补全）', (value) => {
    expect(safeExternalHttpUrl(value)).toBeNull()
  })

  it.each(['http://[broken', 'https://exa mple.com', '://no-scheme', ''])(
    'malformed %s → null',
    (value) => {
      expect(safeExternalHttpUrl(value)).toBeNull()
    },
  )

  it('null → null', () => {
    expect(safeExternalHttpUrl(null)).toBeNull()
  })
})
