/**
 * FIX-309 — 前端只保留一个有界的自动重试层（BASELINE_OK 守卫）。
 *
 * 既有事实（与 BFF 侧 test_r2_fix309_single_retry_layer.py 成对）：
 * 1. main.tsx 全局 QueryClient 默认：4xx 永不重试（404/401/409/429
 *    只付一次请求），网络/5xx 最多重试 2 次（failureCount < 2 上界）；
 *    defaultOptions 不配置 mutations——TanStack mutation 默认 0 次重试，
 *    AI 生成/写操作每次用户动作恰好一次请求；
 * 2. 翻译派发队列（TranslationQueue）每批恰好发送一次：批次失败直接
 *    抛出（不自动重发），取消后不再派发后续批次（N087 已钉取消语义，
 *    这里钉「失败不放大调用数」）。
 *
 * 服务端零自动重试（ai_provider/LibreTranslate 均单次调用）——重试
 * 责任只在 Web 这一层且数量有上界：任何一侧加入自动重试都会叠乘，
 * 本套件与 BFF 侧静态/行为断言共同钉死该不变量。
 */

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

import { TranslationQueue } from '../lib/translation-scope'
import type { ArticleBlock } from '../lib/translation-blocks'

const read = (rel: string): string =>
  readFileSync(resolve(__dirname, '..', rel), 'utf-8')

describe('FIX-309: 前端重试单层且有上界', () => {
  it('main.tsx 查询默认：4xx 永不重试，非 4xx 上界 2 次', () => {
    const main = read('main.tsx')
    expect(main).toContain('retry: (failureCount, error) => {')
    expect(main).toContain('error.status >= 400 && error.status < 500')
    expect(main).toContain('return false')
    expect(main).toContain('return failureCount < 2')
    // mutations 不配置默认重试（TanStack 默认 0）——AI 生成入口
    // 全部是显式 mutation，一次用户动作一次请求。
    expect(main).not.toMatch(/mutations:\s*{[^}]*retry/)
  })

  it('TranslationQueue：批次失败恰好一次请求，绝不自动重发', async () => {
    const blocks: ArticleBlock[] = Array.from({ length: 3 }, (_, i) => ({
      index: i,
      text: `块${i}`,
    }))
    let calls = 0
    const queue = new TranslationQueue(async () => {
      calls += 1
      throw new Error('network down')
    })
    await expect(queue.run(blocks)).rejects.toThrow('network down')
    expect(calls).toBe(1)
  })

  it('TranslationQueue：多批顺序派发，每批恰好一次（成功路径计数）', async () => {
    const blocks: ArticleBlock[] = Array.from({ length: 9 }, (_, i) => ({
      index: i,
      // 1200×5=6000 不超预算，第 6 块才越界 → 每批 5 块 → 9 块 = 2 批。
      text: 'x'.repeat(1200),
    }))
    const sent: number[][] = []
    const queue = new TranslationQueue(async (batch) => {
      sent.push(batch.map((b) => b.index))
    })
    const result = await queue.run(blocks)
    expect(result.cancelled).toBe(false)
    expect(sent).toHaveLength(2)
    expect(sent[0]).toEqual([0, 1, 2, 3, 4])
    expect(sent[1]).toEqual([5, 6, 7, 8])
  })
})
