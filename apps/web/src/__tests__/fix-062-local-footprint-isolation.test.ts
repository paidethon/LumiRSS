/** FIX-062 — 登出/换账号后本机私有足迹清理（localStorage + sessionStorage）。
 *
 * O157 只清了草稿/搜索历史/最近阅读/阅读位置/暂存篮；本批审计发现
 * 还有多个按账号积累的本机键在换账号后原样存活：
 * - 批注离线缓存（lumirss-annotations）——A 的划线/笔记内容；
 * - 阅读会话回顾（lumirss-session-recap-events/-note）——A 的阅读行为；
 * - 阅读路径（lumi-reading-path）、朗读书签（lumi-speech-bookmarks）、
 *   时间线排除批注（lumirss-timeline-excluded-annotations）；
 * - 来源别名离线缓存（lumirss-source-aliases）；
 * - 工作区足迹（最近关闭 / 预览草稿 / 分组折叠）；
 * - 附件下载队列元数据（lumirss-attachment-queue，含文件名）；
 * - 播放续播位置（lumirss-enclosure-positions）；
 * - 搜索命中定位暂存（lumirss-search-hits，sessionStorage 同样在
 *   同一标签页内跨账号存活）。
 *
 * 另验证批注服务端同步标记（serverSyncStarted）随换账号归零——否则
 * B 在同一标签页里永远不触发自己的批注同步。
 */

import { beforeEach, describe, expect, it, vi } from 'vitest'
import { QueryClient } from '@tanstack/react-query'
import { resetAccountState } from '../lib/auth-reset'
import { syncAnnotationsWithServer } from '../lib/annotations'

/** 逐键写入合法 JSON（键名常量不导出的模块按存储契约直接落盘）。 */
function seed(key: string, value: unknown, storage: Storage = localStorage): void {
  storage.setItem(key, JSON.stringify(value))
}

beforeEach(() => {
  localStorage.clear()
  sessionStorage.clear()
})

describe('FIX-062 换账号后本机私有足迹清空', () => {
  it('resetAccountState 清空全部按账号积累的 localStorage/sessionStorage 键', () => {
    seed('lumirss-annotations', [{ id: 'a1', entryRef: 'e1', anchor: {}, note: 'A 的笔记' }])
    seed('lumirss-session-recap-events', [{ at: '2026-09-01T00:00:00Z', kind: 'read' }])
    seed('lumirss-session-recap-note', 'A 的回顾备注')
    seed('lumi-reading-path', { entryRef: 'e1', paraId: 'p1' })
    seed('lumirss-source-aliases', { 'A 的源': 'A 的别名' })
    seed('lumirss-timeline-excluded-annotations', ['ann-1'])
    seed('lumi-speech-bookmarks', [{ entryRef: 'e1', blockIndex: 2, savedAt: 1 }])
    seed('lumi-workspace-recently-closed-v1', [{ ref: 'e1', closedAt: '2026-09-01' }])
    seed('lumi-workspace-preview-drafts-v1', { 'w1': { 'e1': 'A 的预览草稿' } })
    seed('lumi-workspace-groups-collapsed-v1', { 'w1': ['组一'] })
    seed('lumirss-attachment-queue', [{ id: 'q1', name: 'A 的附件.pdf' }])
    seed('lumirss-enclosure-positions', { 'e1.a': 42.5 })
    seed('lumirss-search-hits', { e1: [] }, sessionStorage)

    resetAccountState(new QueryClient())

    for (const key of [
      'lumirss-annotations',
      'lumirss-session-recap-events',
      'lumirss-session-recap-note',
      'lumirss-source-aliases',
      'lumi-speech-bookmarks',
      'lumi-workspace-recently-closed-v1',
      'lumi-workspace-preview-drafts-v1',
      'lumi-workspace-groups-collapsed-v1',
      'lumirss-attachment-queue',
      'lumirss-enclosure-positions',
    ]) {
      expect(localStorage.getItem(key), key).toBeNull()
    }
    expect(sessionStorage.getItem('lumirss-search-hits')).toBeNull()

    // 这两处 clear 语义是「重置为空态」而非移除键：内容已清空即达标。
    expect(JSON.parse(localStorage.getItem('lumirss-timeline-excluded-annotations') ?? '["x"]')).toEqual([])
    expect(JSON.parse(localStorage.getItem('lumi-reading-path') ?? '{}')).toEqual({
      enabled: true,
      entries: [],
    })
  })

  it('批注服务端同步标记随换账号归零：reset 后 sync 会重新发起网络同步', async () => {
    const annotation = {
      id: 'srv-1',
      entryRef: 'e1',
      anchor: { exact: 'text' },
      excerpt: 'text',
      note: '',
      color: 'yellow',
      createdAt: '2026-09-01T00:00:00Z',
      updatedAt: '2026-09-01T00:00:00Z',
    }
    const fetchMock = vi.fn(async (url: unknown, init?: RequestInit) => {
      const path = String(url)
      const method = init?.method ?? 'GET'
      if (path === '/api/v1/annotations' && method === 'POST') {
        return new Response(JSON.stringify(annotation), { status: 201 })
      }
      if (path.startsWith('/api/v1/annotations') && method === 'GET') {
        return new Response(JSON.stringify({ items: [annotation], nextCursor: null }), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        })
      }
      return new Response(JSON.stringify({ error: { type: 'not_found' } }), { status: 404 })
    })
    vi.stubGlobal('fetch', fetchMock)

    // A 会话首次同步：成功 → 标记置位（后续调用 no-op）。
    seed('lumirss-annotations', [{ id: 'local-1', entryRef: 'e1', anchor: {}, note: 'x' }])
    await syncAnnotationsWithServer()
    await syncAnnotationsWithServer()
    const callsAfterFirstSync = fetchMock.mock.calls.length
    await syncAnnotationsWithServer()
    expect(fetchMock.mock.calls.length).toBe(callsAfterFirstSync)

    // 换账号：缓存清空 + 标记归零 → B 的 Reader 挂载能触发自己的同步。
    resetAccountState(new QueryClient())
    expect(localStorage.getItem('lumirss-annotations')).toBeNull()
    await syncAnnotationsWithServer()
    expect(fetchMock.mock.calls.length).toBeGreaterThan(callsAfterFirstSync)

    vi.unstubAllGlobals()
  })
})
