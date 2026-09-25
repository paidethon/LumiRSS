/** N065 附件下载队列 — 纯逻辑 + AttachmentQueuePanel 接线（jsdom）。
 *
 * 覆盖：入队/进度/取消/重试一次（fetch mock：ReadableStream / abort）；
 * 白名单外扩展名拒绝（脚本/可执行）；重复 URL 忽略；200MB 上限 LRU
 * 逐出 + 诚实提示；单条超限拒绝；文件名净化（保留 CJK、剥路径）。 */

import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import AttachmentQueuePanel from '../components/AttachmentQueuePanel'
import {
  ALLOWED_ATTACHMENT_EXTENSIONS,
  formatAttachmentBytes,
  ATTACHMENT_QUEUE_CAP_BYTES,
  ATTACHMENT_QUEUE_STORAGE_KEY,
  attachmentExtension,
  attachmentFilenameFromUrl,
  isAllowedAttachment,
  normalizeAttachmentQueue,
  planQueueCapacity,
  readAttachmentQueue,
  sanitizeAttachmentFilename,
  type AttachmentQueueItem,
} from '../lib/attachment-queue'
import type { EntryDetail } from '../api/types'

function detailFixture(enclosure: { href: string; type?: string | null }[]): EntryDetail {
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
    enclosure,
  }
}

/** 流式 Response：两块（5 + 7 字节）+ content-length 12。 */
function streamResponse(): Response {
  const encoder = new TextEncoder()
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(encoder.encode('hello'))
      controller.enqueue(encoder.encode(' world'))
      controller.close()
    },
  })
  return new Response(stream, {
    status: 200,
    headers: { 'content-length': '12', 'content-type': 'application/pdf' },
  })
}

/** 永不完成的下载（abort 时以 AbortError 拒绝）。 */
function hangingResponse(): { response: Response; abortOf: (signal: AbortSignal) => void } {
  let rejectBody: ((reason: unknown) => void) | null = null
  const promise = new Promise<Uint8Array>((_, reject) => {
    rejectBody = reject
  })
  const stream = new ReadableStream<Uint8Array>({
    pull() {
      return promise as unknown as Promise<void>
    },
  })
  const response = new Response(stream, {
    status: 200,
    headers: { 'content-type': 'audio/mpeg' },
  })
  // Response 包装后无法直接 reject —— 通过 mock fetch 的 signal 兜底：
  // 挂到 response 上不可行，改为在 fetch mock 中注册。
  return { response, abortOf: (signal) => {
    signal.addEventListener('abort', () => {
      rejectBody?.(Object.assign(new Error('The operation was aborted.'), { name: 'AbortError' }))
    })
  } }
}

beforeEach(() => {
  window.localStorage.clear()
  // jsdom 无 blob URL：stub（下载触发路径的行为可测）
  URL.createObjectURL = vi.fn(() => 'blob:mock')
  URL.revokeObjectURL = vi.fn()
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('attachment-queue 纯逻辑', () => {
  it('扩展名白名单：音频/视频/图片/PDF/EPUB 放行；脚本与可执行拒绝', () => {
    for (const ext of ['mp3', 'mp4', 'pdf', 'epub', 'png']) {
      expect(ALLOWED_ATTACHMENT_EXTENSIONS).toContain(ext)
    }
    expect(isAllowedAttachment('https://cdn.example.com/episode.mp3', 'audio/mpeg')).toBe(true)
    expect(isAllowedAttachment('https://cdn.example.com/episode', 'audio/mpeg')).toBe(true)
    expect(isAllowedAttachment('https://cdn.example.com/paper.pdf', null)).toBe(true)
    // 脚本 / 可执行：无论 MIME 如何伪装都拒绝
    expect(isAllowedAttachment('https://evil.example.com/payload.exe', 'audio/mpeg')).toBe(false)
    expect(isAllowedAttachment('https://evil.example.com/run.sh')).toBe(false)
    expect(isAllowedAttachment('https://evil.example.com/page.html', 'text/html')).toBe(false)
    expect(isAllowedAttachment('https://evil.example.com/app.js', 'text/javascript')).toBe(false)
    // 白名单外 + 无 MIME → 拒绝（不猜）
    expect(isAllowedAttachment('https://example.com/file.xyz')).toBe(false)
  })

  it('attachmentExtension / sanitizeAttachmentFilename：剥路径保留 CJK', () => {
    expect(attachmentExtension('https://x.test/a/b/节目.mp3?token=1')).toBe('mp3')
    expect(attachmentExtension('https://x.test/noext')).toBe('')
    expect(sanitizeAttachmentFilename('../../etc/passwd')).toBe('....etcpasswd')
    expect(sanitizeAttachmentFilename('中文 节目.mp3')).toBe('中文 节目.mp3')
    expect(sanitizeAttachmentFilename('bad/name\\here.txt')).toBe('badnamehere.txt')
    expect(sanitizeAttachmentFilename('..')).toBe('attachment')
    expect(sanitizeAttachmentFilename('')).toBe('attachment')
    expect(attachmentFilenameFromUrl('https://x.test/pod/%E6%95%99%E7%A8%8B.mp3')).toBe(
      '教程.mp3',
    )
  })

  it('planQueueCapacity：LRU 逐出最旧并返回逐出清单；单条超限拒绝', () => {
    const cap = 1000
    const item = (id: string, size: number, addedAt: number, status: AttachmentQueueItem['status'] = 'done'): AttachmentQueueItem => ({
      id,
      url: `https://x.test/${id}`,
      name: id,
      size,
      status,
      progress: status === 'done' ? 100 : 0,
      loaded: 0,
      error: null,
      addedAt,
      retries: 0,
    })
    // 600 + 600 > 1000：加入 600 时逐出最旧（addedAt 小者）；cap 1200
    // 恰好容纳 new(600) + incoming(600)
    const plan = planQueueCapacity([item('old', 600, 1), item('new', 600, 2)], 600, 1200)
    expect(plan.overCap).toBe(false)
    expect(plan.evicted.map((i) => i.id)).toEqual(['old'])
    expect(plan.kept.map((i) => i.id)).toEqual(['new'])
    // 单条自身超限 → overCap（拒绝加入）
    const reject = planQueueCapacity([], 2000, cap)
    expect(reject.overCap).toBe(true)
    // 放得下 → 不逐出
    const fine = planQueueCapacity([item('a', 100, 1)], 100, cap)
    expect(fine.evicted).toHaveLength(0)
    expect(ATTACHMENT_QUEUE_CAP_BYTES).toBe(200 * 1024 * 1024)
  })
})

describe('AttachmentQueuePanel 接线', () => {
  it('下载：流式进度→完成；完成经 anchor 触发浏览器下载', async () => {
    const fetchMock = vi.fn(() => Promise.resolve(streamResponse()))
    vi.stubGlobal('fetch', fetchMock)
    const createObjectURL = URL.createObjectURL as ReturnType<typeof vi.fn>
    render(<AttachmentQueuePanel detail={detailFixture([{ href: 'https://cdn.test/ep1.mp3', type: 'audio/mpeg' }])} />)

    const add = screen.getByTestId('attachment-add')
    fireEvent.click(add)

    // 完成：状态行变为已下载（含实际字节数）；fetch 携带 abort 信号
    await waitFor(() => expect(screen.getByText(/已下载/)).toBeInTheDocument())
    expect(fetchMock).toHaveBeenCalledWith('https://cdn.test/ep1.mp3', expect.objectContaining({ signal: expect.anything() }))
    // 完成 → object URL + anchor 下载
    await waitFor(() => expect(createObjectURL).toHaveBeenCalled())
    const stored = readAttachmentQueue()
    expect(stored).toHaveLength(1)
    expect(stored[0]!.status).toBe('done')
    expect(stored[0]!.size).toBe(11) // hello(5) + " world"(6)
    expect(window.localStorage.getItem(ATTACHMENT_QUEUE_STORAGE_KEY)).toContain('ep1.mp3')
  })

  it('取消：在途项取消后状态诚实标为已取消', async () => {
    const hanging = hangingResponse()
    const fetchMock = vi.fn((_input: RequestInfo | URL, init?: RequestInit) => {
      const signal = init?.signal
      if (signal !== null && signal !== undefined) hanging.abortOf(signal)
      return Promise.resolve(hanging.response)
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<AttachmentQueuePanel detail={detailFixture([{ href: 'https://cdn.test/long.mp3', type: 'audio/mpeg' }])} />)

    fireEvent.click(screen.getByTestId('attachment-add'))
    await waitFor(() => expect(screen.getByTestId('attachment-status').textContent).toContain('下载中'))

    fireEvent.click(screen.getByRole('button', { name: '取消下载 long.mp3' }))
    await waitFor(() => expect(screen.getByTestId('attachment-status').textContent).toContain('已取消'))
    expect(readAttachmentQueue()[0]!.status).toBe('canceled')
  })

  it('失败重试一次：失败后重试可用一次，再次失败后不再提供重试', async () => {
    let calls = 0
    const fetchMock = vi.fn(() => {
      calls += 1
      return Promise.resolve(new Response('nope', { status: 500 }))
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<AttachmentQueuePanel detail={detailFixture([{ href: 'https://cdn.test/broken.mp3', type: 'audio/mpeg' }])} />)

    fireEvent.click(screen.getByTestId('attachment-add'))
    await waitFor(() => expect(screen.getByTestId('attachment-status').textContent).toContain('失败'))

    // 第一次重试：允许
    fireEvent.click(screen.getByRole('button', { name: '重试下载 broken.mp3' }))
    await waitFor(() => expect(calls).toBe(2))
    await waitFor(() => expect(screen.getByTestId('attachment-status').textContent).toContain('失败'))
    // retry-once：第二次失败后不再提供重试入口
    expect(screen.queryByRole('button', { name: '重试下载 broken.mp3' })).toBeNull()
    expect(readAttachmentQueue()[0]!.retries).toBe(1)
  })

  it('重复 URL 忽略：入队后同 URL 不再提供下载入口；归一化按 URL 去重', async () => {
    const hanging = hangingResponse()
    const fetchMock = vi.fn((_input: RequestInfo | URL, init?: RequestInit) => {
      const signal = init?.signal
      if (signal !== null && signal !== undefined) hanging.abortOf(signal)
      return Promise.resolve(hanging.response)
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<AttachmentQueuePanel detail={detailFixture([{ href: 'https://cdn.test/dup.mp3', type: 'audio/mpeg' }])} />)

    fireEvent.click(screen.getByTestId('attachment-add'))
    // 入队后同一 enclosure 行切换为队列状态：add 入口消失（同 URL 不可重复入队）
    await waitFor(() => expect(screen.queryByTestId('attachment-add')).toBeNull())
    // 队列归一化（localStorage 加载路径）对重复 URL 去重（单条数据保障）
    const deduped = normalizeAttachmentQueue([
      { id: 'a', url: 'https://x.test/same.mp3', name: 'a.mp3', status: 'done', addedAt: 1 },
      { id: 'b', url: 'https://x.test/same.mp3', name: 'b.mp3', status: 'done', addedAt: 2 },
    ])
    expect(deduped).toHaveLength(1)
    expect(readAttachmentQueue()).toHaveLength(1)
    await act(async () => {})
  })

  it('白名单外类型：不提供下载入口，诚实标注不支持', () => {
    render(
      <AttachmentQueuePanel
        detail={detailFixture([
          { href: 'https://evil.test/payload.exe', type: null },
          { href: 'https://ok.test/ep.mp3', type: 'audio/mpeg' },
        ])}
      />,
    )
    // exe 无下载按钮且有诚实标注；mp3 可下载
    expect(screen.getAllByText('不支持下载')).toHaveLength(1)
    expect(screen.queryByTestId('attachment-add')).not.toBeNull()
    expect(screen.getByRole('button', { name: /下载/ }).textContent).toContain('下载')
  })

  it('容量上限：放不下时 LRU 逐出旧记录并诚实提示', () => {
    window.localStorage.setItem(
      ATTACHMENT_QUEUE_STORAGE_KEY,
      JSON.stringify([
        {
          id: 'a1',
          url: 'https://x.test/a1.mp3',
          name: 'a1.mp3',
          size: 190 * 1024 * 1024,
          status: 'done',
          progress: 100,
          loaded: 0,
          error: null,
          addedAt: 1,
          retries: 0,
        },
        {
          id: 'a2',
          url: 'https://x.test/a2.mp3',
          name: 'a2.mp3',
          size: 190 * 1024 * 1024,
          status: 'done',
          progress: 100,
          loaded: 0,
          error: null,
          addedAt: 2,
          retries: 0,
        },
      ]),
    )
    render(<AttachmentQueuePanel detail={detailFixture([{ href: 'https://cdn.test/next.mp3', type: 'audio/mpeg' }])} />)
    fireEvent.click(screen.getByTestId('attachment-add'))
    // 190+190 已超 200MB：入队时逐出最旧记录（a1），面板给出诚实提示
    expect(screen.getByTestId('attachment-queue-notice').textContent).toContain('清理')
    expect(screen.getByTestId('attachment-queue-notice').textContent).toContain('最旧')
    const kept = readAttachmentQueue()
    expect(kept.some((item) => item.id === 'a1')).toBe(false)
    expect(kept.some((item) => item.url === 'https://cdn.test/next.mp3')).toBe(true)
  })

  it('遗留 downloading 元数据：挂载时诚实转为失败（可重试），不再假「下载中」', () => {
    window.localStorage.setItem(
      ATTACHMENT_QUEUE_STORAGE_KEY,
      JSON.stringify([
        {
          id: 'stuck',
          url: 'https://cdn.test/ep.mp3',
          name: 'ep.mp3',
          size: null,
          status: 'downloading',
          progress: 40,
          loaded: 100,
          error: null,
          addedAt: 1,
          retries: 0,
        },
      ]),
    )
    render(<AttachmentQueuePanel detail={detailFixture([{ href: 'https://cdn.test/ep.mp3', type: 'audio/mpeg' }])} />)
    // 挂载即归一：上次中断的下载显示失败原因（而非永远「下载中」）
    expect(screen.getByTestId('attachment-status').textContent).toContain('失败')
    expect(screen.getByTestId('attachment-status').textContent).toContain('中断')
    // 重试一次可用
    expect(screen.getByRole('button', { name: '重试下载 ep.mp3' })).not.toBeNull()
    expect(readAttachmentQueue()[0]!.status).toBe('failed')
  })

  it('formatAttachmentBytes：未知大小诚实显示', () => {
    expect(formatAttachmentBytes(null)).toBe('大小未知')
    expect(formatAttachmentBytes(512)).toBe('512 B')
    expect(formatAttachmentBytes(2048)).toBe('2 KB')
    expect(formatAttachmentBytes(3 * 1024 * 1024)).toBe('3.0 MB')
  })
})
