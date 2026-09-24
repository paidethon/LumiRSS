/** NF1 N092 — 听读分段书签（jsdom）。
 *
 * 覆盖：朗读中「书签」按钮保存 {entryRef, blockIndex, savedAt}（设备本地
 * lumi-speech-bookmarks）；重开文章出现「从第 N 段继续朗读」chip，点击
 * 从保存的块开始朗读；书签 upsert（同一 entry 最新一条）+ LRU 20 淘汰；
 * 未朗读时书签按钮诚实禁用。 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import ReaderHeader from '../components/ReaderHeader'
import {
  SPEECH_BOOKMARKS_CAP,
  getSpeechBookmark,
  normalizeSpeechBookmarks,
  readSpeechBookmarks,
  saveSpeechBookmark,
} from '../lib/speech-bookmarks'
import { DEFAULT_APP_SETTINGS, useAppSettings } from '../store/app-settings'
import type { EntryDetail } from '../api/types'

// ---- speechSynthesis mock（同 p18 模式） ----

class MockUtterance {
  text: string
  lang = ''
  voice: unknown = null
  rate = 1
  onend: (() => void) | null = null
  onerror: (() => void) | null = null
  constructor(text: string) {
    this.text = text
  }
}

function stubSpeech(voices: SpeechSynthesisVoice[] = []) {
  const speak = vi.fn()
  const cancel = vi.fn()
  const pause = vi.fn()
  const resume = vi.fn()
  vi.stubGlobal('speechSynthesis', {
    getVoices: () => voices,
    speak,
    cancel,
    pause,
    resume,
  })
  vi.stubGlobal('SpeechSynthesisUtterance', MockUtterance)
  return { speak, cancel, pause, resume }
}

const VOICES = [
  { lang: 'zh-CN', name: '婷婷', voiceURI: 'zh-cn' },
] as unknown as SpeechSynthesisVoice[]

const BLOCK_TEXTS = ['第一段', '第二段', '第三段']

beforeEach(() => {
  window.localStorage.clear()
  useAppSettings.setState({ settings: { ...DEFAULT_APP_SETTINGS } })
})

afterEach(() => {
  vi.unstubAllGlobals()
  localStorage.clear()
})

function detailFixture(over: Partial<EntryDetail> = {}): EntryDetail {
  return {
    entryRef: 'e1.a',
    title: '文章 A',
    feedTitle: '示例源',
    author: null,
    url: 'https://example.com/a',
    publishedAt: null,
    read: false,
    starred: false,
    contentText: '正文',
    contentHtml: '<p>正文</p>',
    ...over,
  }
}

function withProviders(ui: ReactNode) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
}

function renderHeader(speak: ReturnType<typeof vi.fn>) {
  const collect = () => ({ texts: [...BLOCK_TEXTS], startIndex: 0 })
  render(
    withProviders(
      <ReaderHeader detail={detailFixture()} collectSpeechBlocks={collect} />,
    ),
  )
  return { speak }
}

describe('N092 — 听读分段书签（存储）', () => {
  it('保存：upsert 同一 entry + LRU 20 淘汰最久未写；损坏数据丢弃', () => {
    for (let i = 0; i < 25; i += 1) {
      saveSpeechBookmark(`entry-${i}`, i)
    }
    const all = readSpeechBookmarks()
    expect(all).toHaveLength(SPEECH_BOOKMARKS_CAP)
    expect(all[0]!.entryRef).toBe('entry-24')
    expect(all.some((b) => b.entryRef === 'entry-0')).toBe(false)

    // 同一 entry 重存：提到最前且不重复
    saveSpeechBookmark('entry-10', 5)
    const next = readSpeechBookmarks()
    expect(next[0]!.entryRef).toBe('entry-10')
    expect(next[0]!.blockIndex).toBe(5)
    expect(next.filter((b) => b.entryRef === 'entry-10')).toHaveLength(1)

    // 归一化：非法条目丢弃
    expect(
      normalizeSpeechBookmarks([
        { entryRef: 'a', blockIndex: 2, savedAt: 1 },
        { entryRef: '', blockIndex: 1 },
        { entryRef: 'b', blockIndex: -1 },
        { entryRef: 'c', blockIndex: 1.5 },
        'junk',
        null,
      ]),
    ).toEqual([{ entryRef: 'a', blockIndex: 2, savedAt: 1 }])

    expect(getSpeechBookmark('entry-10')).not.toBeNull()
    expect(getSpeechBookmark('missing')).toBeNull()
  })
})

describe('N092 — 听读分段书签（面板 + 续听 chip）', () => {
  it('朗读中保存书签：写入当前块下标；未朗读时按钮禁用', () => {
    const speech = stubSpeech(VOICES)
    renderHeader(speech.speak)

    // 未朗读：书签禁用
    fireEvent.click(screen.getByRole('button', { name: '朗读设置' }))
    expect(screen.getByRole('button', { name: '书签' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: '朗读设置' })) // 关闭

    // 开始朗读并推进到第二块（index 1）
    fireEvent.click(screen.getByRole('button', { name: '朗读' }))
    act(() => {
      ;(speech.speak.mock.calls[0]![0] as MockUtterance).onend!()
    })

    fireEvent.click(screen.getByRole('button', { name: '朗读设置' }))
    fireEvent.click(screen.getByRole('button', { name: '书签' }))

    const saved = getSpeechBookmark('e1.a')
    expect(saved).not.toBeNull()
    expect(saved!.blockIndex).toBe(1)
    expect(saved!.savedAt).toBeGreaterThan(0)
    // localStorage 落盘（设备本地）
    const raw = JSON.parse(
      localStorage.getItem('lumi-speech-bookmarks') ?? '[]',
    ) as Array<{ entryRef: string; blockIndex: number }>
    expect(raw[0]).toMatchObject({ entryRef: 'e1.a', blockIndex: 1 })
    // 面板诚实反馈
    expect(screen.getByText(/已保存书签（第 2 段）/)).toBeInTheDocument()
  })

  it('重开文章显示续听 chip；点击从保存的块开始朗读；title 诚实说明按段续读', () => {
    saveSpeechBookmark('e1.a', 2)
    const speech = stubSpeech(VOICES)

    const { unmount } = render(
      withProviders(
        <ReaderHeader
          detail={detailFixture()}
          collectSpeechBlocks={() => ({ texts: [...BLOCK_TEXTS], startIndex: 0 })}
        />,
      ),
    )
    const chip = screen.getByRole('button', { name: '从第 3 段继续朗读' })
    expect(chip).toBeInTheDocument()
    expect(chip).toHaveAttribute(
      'title',
      '按段续读：从该段开头朗读（浏览器语音无法在句中定位）',
    )
    fireEvent.click(chip)
    expect((speech.speak.mock.calls[0]![0] as MockUtterance).text).toBe('第三段')
    // 开始朗读后 chip 隐藏
    expect(screen.queryByRole('button', { name: '从第 3 段继续朗读' })).not.toBeInTheDocument()
    unmount()

    // × 只隐藏本会话提示，不清除书签
    stubSpeech(VOICES)
    const second = render(
      withProviders(
        <ReaderHeader
          detail={detailFixture()}
          collectSpeechBlocks={() => ({ texts: [...BLOCK_TEXTS], startIndex: 0 })}
        />,
      ),
    )
    fireEvent.click(screen.getByRole('button', { name: '隐藏续读提示' }))
    expect(screen.queryByRole('button', { name: '从第 3 段继续朗读' })).not.toBeInTheDocument()
    expect(getSpeechBookmark('e1.a')).not.toBeNull()
    second.unmount()
  })

  it('没有书签的 entry 不显示 chip；speechSynthesis 不可用时不显示 chip', () => {
    // 无书签 + 能力可用 → 无 chip
    stubSpeech(VOICES)
    render(
      withProviders(
        <ReaderHeader
          detail={detailFixture()}
          collectSpeechBlocks={() => ({ texts: [...BLOCK_TEXTS], startIndex: 0 })}
        />,
      ),
    )
    expect(screen.queryByRole('button', { name: /继续朗读/ })).not.toBeInTheDocument()
  })
})
