/** NEW-355 单篇媒体流量预算 — 纯逻辑 + 面板（jsdom）。
 *
 * 覆盖：单篇决策存取（损坏回退 / 'ask' 不落盘 / 逐篇隔离）；已知体积
 * 仅来自本机附件队列（同 URL done+size）；预算汇总（未知计数 / 已知
 * 合计 / 不做任何网络请求）；面板主路径（显示图片与附件、策略选择
 * 持久化、模式说明）。 */

import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import MediaBudgetPanel, { collectImageSrcs } from '../components/new351/MediaBudgetPanel'
import {
  MEDIA_BUDGET_STORAGE_KEY,
  budgetRequiresDefer,
  estimateMediaBudget,
  knownBytesForUrl,
  readMediaBudgetDecision,
  writeMediaBudgetDecision,
} from '../lib/media-budget'
import { ATTACHMENT_QUEUE_STORAGE_KEY } from '../lib/attachment-queue'

beforeEach(() => {
  window.localStorage.clear()
})

describe('NEW-355 预算纯逻辑', () => {
  it('单篇决策存取：逐篇隔离；损坏 JSON / 非法值 → null（回退 ask）；ask 移除键', () => {
    expect(readMediaBudgetDecision('rss:e1')).toBeNull()
    writeMediaBudgetDecision('rss:e1', 'text-only')
    writeMediaBudgetDecision('rss:e2', 'per-load')
    expect(readMediaBudgetDecision('rss:e1')?.mode).toBe('text-only')
    expect(readMediaBudgetDecision('rss:e2')?.mode).toBe('per-load')
    expect(readMediaBudgetDecision('rss:e3')).toBeNull()
    writeMediaBudgetDecision('rss:e1', 'ask')
    expect(readMediaBudgetDecision('rss:e1')).toBeNull()
    // 损坏
    window.localStorage.setItem(MEDIA_BUDGET_STORAGE_KEY, '{broken')
    expect(readMediaBudgetDecision('rss:e2')).toBeNull()
  })

  it('已知体积只来自本机附件队列（同 URL + done + size）；否则未知', () => {
    window.localStorage.setItem(
      ATTACHMENT_QUEUE_STORAGE_KEY,
      JSON.stringify([
        { id: 'a1', url: 'https://cdn.example.com/ep1.mp3', name: 'ep1.mp3', size: 1048576, status: 'done', progress: 100, loaded: 1048576, error: null, addedAt: 1, retries: 0 },
        { id: 'a2', url: 'https://cdn.example.com/ep2.mp3', name: 'ep2.mp3', size: null, status: 'done', progress: 0, loaded: 512, error: null, addedAt: 2, retries: 0 },
        { id: 'a3', url: 'https://cdn.example.com/ep3.mp3', name: 'ep3.mp3', size: 999, status: 'failed', progress: 0, loaded: 0, error: 'x', addedAt: 3, retries: 0 },
      ]),
    )
    expect(knownBytesForUrl('https://cdn.example.com/ep1.mp3')).toBe(1048576)
    expect(knownBytesForUrl('https://cdn.example.com/ep2.mp3')).toBeNull()
    expect(knownBytesForUrl('https://cdn.example.com/ep3.mp3')).toBeNull()
    expect(knownBytesForUrl('https://cdn.example.com/never-seen.mp3')).toBeNull()
  })

  it('预算汇总：图片计数（未知）+ 附件已知体积合计 + 未知计数', () => {
    window.localStorage.setItem(
      ATTACHMENT_QUEUE_STORAGE_KEY,
      JSON.stringify([
        { id: 'a1', url: 'https://cdn.example.com/ep1.mp3', name: 'ep1.mp3', size: 1000, status: 'done', progress: 100, loaded: 1000, error: null, addedAt: 1, retries: 0 },
      ]),
    )
    const estimate = estimateMediaBudget({
      imageSrcs: ['https://img.example.com/a.jpg', 'https://img.example.com/b.jpg'],
      enclosures: [{ href: 'https://cdn.example.com/ep1.mp3', type: 'audio/mpeg' }],
    })
    expect(estimate.imageCount).toBe(2)
    expect(estimate.enclosureCount).toBe(1)
    expect(estimate.knownTotalBytes).toBe(1000)
    expect(estimate.unknownCount).toBe(2)
  })

  it('策略 → 延后管线的映射：text-only / per-load 需要占位，ask 不需要', () => {
    expect(budgetRequiresDefer('text-only')).toBe(true)
    expect(budgetRequiresDefer('per-load')).toBe(true)
    expect(budgetRequiresDefer('ask')).toBe(false)
  })

  it('图片 src 收集：来自 src 或已摘除的 data-lumi-src；零请求（无 fetch）', () => {
    const fetchSpy = vi.fn()
    vi.stubGlobal('fetch', fetchSpy)
    expect(collectImageSrcs('<img src="https://a.example/x.jpg"><img data-lumi-src="https://a.example/y.jpg">')).toEqual([
      'https://a.example/x.jpg',
      'https://a.example/y.jpg',
    ])
    expect(collectImageSrcs('<p>无图</p>')).toEqual([])
    expect(collectImageSrcs(null)).toEqual([])
    expect(fetchSpy).not.toHaveBeenCalled()
    vi.unstubAllGlobals()
  })
})

describe('NEW-355 预算面板', () => {
  it('显示图片/附件汇总与逐项体积（未知如实标注）；策略选择持久化', () => {
    window.localStorage.setItem(
      ATTACHMENT_QUEUE_STORAGE_KEY,
      JSON.stringify([
        { id: 'a1', url: 'https://cdn.example.com/ep1.mp3', name: 'ep1.mp3', size: 1000, status: 'done', progress: 100, loaded: 1000, error: null, addedAt: 1, retries: 0 },
      ]),
    )
    render(
      <MediaBudgetPanel
        entryRef="rss:e1"
        contentHtml={'<p>正文</p><img src="https://img.example.com/a.jpg">'}
        enclosures={[{ href: 'https://cdn.example.com/ep1.mp3', type: 'audio/mpeg' }]}
        onClose={() => {}}
      />,
    )
    expect(screen.getByText(/图片 1 张 · 媒体附件 1 个/)).toBeTruthy()
    expect(screen.getByText(/1 项体积未知/)).toBeTruthy()
    expect(screen.getByText('体积未知')).toBeTruthy()
    expect(screen.getByText(/ep1\.mp3/)).toBeTruthy()
    // 选择只读文字 → 持久化 + 模式说明出现
    fireEvent.click(screen.getByLabelText('只读文字（图片与音频保持占位）'))
    expect(readMediaBudgetDecision('rss:e1')?.mode).toBe('text-only')
    expect(screen.getByText(/只读文字：本篇图片保持占位/)).toBeTruthy()
  })

  it('无媒体本篇 → 空清单诚实提示；零网络请求', () => {
    const fetchSpy = vi.fn()
    vi.stubGlobal('fetch', fetchSpy)
    render(
      <MediaBudgetPanel
        entryRef="rss:e1"
        contentHtml={'<p>纯文字</p>'}
        enclosures={[]}
        onClose={() => {}}
      />,
    )
    expect(screen.getByText('本篇没有图片或媒体附件。')).toBeTruthy()
    expect(fetchSpy).not.toHaveBeenCalled()
    vi.unstubAllGlobals()
  })
})
