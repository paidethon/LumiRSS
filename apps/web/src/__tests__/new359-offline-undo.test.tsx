/** NEW-359 离线阅读撤销栈 — 纯逻辑 + 面板（jsdom）。
 *
 * 覆盖：记录（成功=synced / 离线失败=pending 的判定）；去重只留最新 /
 * 有界逐出；逐项撤销仅 pending、synced 明确拒绝；清空；面板两段式
 * 呈现与「已同步不能直接撤销」的如实提示。 */

import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import OfflineUndoPanel from '../components/new351/OfflineUndoPanel'
import {
  OFFLINE_UNDO_STACK_LIMIT,
  OFFLINE_UNDO_STORAGE_KEY,
  canUndoOfflineEntry,
  clearOfflineUndoStack,
  isNetworkFailure,
  readOfflineUndoStack,
  recordOfflineUndo,
  shouldRecordAsPending,
  shouldRecordAsPendingFromFailure,
  undoOfflineEntry,
} from '../lib/offline-undo-stack'

beforeEach(() => {
  window.localStorage.clear()
})

describe('NEW-359 撤销栈纯逻辑', () => {
  it('记录：离线 → pending（可撤销）；在线成功 → synced（不可撤销）', () => {
    expect(shouldRecordAsPending(false)).toBe(true)
    expect(shouldRecordAsPending(true)).toBe(false)
    recordOfflineUndo({ kind: 'read', entryRef: 'rss:e1', syncState: 'pending' })
    recordOfflineUndo({ kind: 'star', entryRef: 'rss:e2', syncState: 'synced' })
    const stack = readOfflineUndoStack()
    expect(stack.map((e) => [e.kind, e.syncState])).toEqual([
      ['star', 'synced'],
      ['read', 'pending'],
    ])
    expect(stack[1]!.label).toBe('标为已读')
    expect(canUndoOfflineEntry(stack[0]!)).toBe(false)
    expect(canUndoOfflineEntry(stack[1]!)).toBe(true)
  })

  it('同 kind+entryRef 去重只留最新；超限逐出最旧', () => {
    recordOfflineUndo({ kind: 'read', entryRef: 'rss:e1', syncState: 'pending' })
    const refreshed = recordOfflineUndo({ kind: 'read', entryRef: 'rss:e1', syncState: 'synced' })
    const stack = readOfflineUndoStack()
    expect(stack.length).toBe(1)
    expect(stack[0]!.id).toBe(refreshed.id)
    for (let i = 0; i < OFFLINE_UNDO_STACK_LIMIT + 3; i += 1) {
      recordOfflineUndo({ kind: 'readLater', entryRef: `rss:x${i}`, syncState: 'synced' })
    }
    expect(readOfflineUndoStack().length).toBe(OFFLINE_UNDO_STACK_LIMIT)
  })

  it('逐项撤销：pending 移除并返回条目；synced 拒绝（返回 null，栈不变）', () => {
    const pending = recordOfflineUndo({ kind: 'read', entryRef: 'rss:e1', syncState: 'pending' })
    const synced = recordOfflineUndo({ kind: 'star', entryRef: 'rss:e2', syncState: 'synced' })
    const removed = undoOfflineEntry(pending.id)
    expect(removed?.entryRef).toBe('rss:e1')
    expect(readOfflineUndoStack().map((e) => e.id)).toEqual([synced.id])
    expect(undoOfflineEntry(synced.id)).toBeNull()
    expect(readOfflineUndoStack().length).toBe(1)
    expect(undoOfflineEntry('missing-id')).toBeNull()
  })

  it('清空（换账号 / 显式清空共用）', () => {
    recordOfflineUndo({ kind: 'read', entryRef: 'rss:e1', syncState: 'pending' })
    clearOfflineUndoStack()
    expect(window.localStorage.getItem(OFFLINE_UNDO_STORAGE_KEY)).toBeNull()
    expect(readOfflineUndoStack()).toEqual([])
  })

  it('损坏 JSON → 空栈（诚实回退）', () => {
    window.localStorage.setItem(OFFLINE_UNDO_STORAGE_KEY, 'not-json')
    expect(readOfflineUndoStack()).toEqual([])
  })
})

describe('FIX-346 真实网络失败识别（navigator.onLine 只是旁证）', () => {
  it('在线但 fetch 层失败（ApiError status=0 + type=network_error）→ pending 入栈', () => {
    const networkFailure = Object.assign(new Error('无法连接到服务器，请稍后重试。'), {
      status: 0,
      type: 'network_error',
    })
    expect(shouldRecordAsPendingFromFailure(true, networkFailure)).toBe(true)
    expect(isNetworkFailure(networkFailure)).toBe(true)
  })

  it('服务端明确拒绝（4xx/5xx）→ 不入栈（服务端事实，不是待同步意图）', () => {
    const serverRejected = Object.assign(new Error('bad request'), { status: 400, type: 'validation' })
    expect(shouldRecordAsPendingFromFailure(true, serverRejected)).toBe(false)
    expect(isNetworkFailure(serverRejected)).toBe(false)
    expect(shouldRecordAsPendingFromFailure(true, new Error('plain boom'))).toBe(false)
    expect(shouldRecordAsPendingFromFailure(true, undefined)).toBe(false)
  })

  it('设备离线 → 无论错误形状一律 pending（原语义保持）', () => {
    expect(shouldRecordAsPendingFromFailure(false, undefined)).toBe(true)
    expect(shouldRecordAsPendingFromFailure(false, serverRejected404())).toBe(true)
  })

  function serverRejected404(): Error {
    return Object.assign(new Error('not found'), { status: 404, type: 'not_found' })
  }
})

describe('NEW-359 撤销栈面板', () => {
  it('两段式呈现：未同步可逐项撤销；已同步锁定并如实提示拒绝', () => {
    recordOfflineUndo({ kind: 'read', entryRef: 'rss:e1', syncState: 'pending' })
    recordOfflineUndo({ kind: 'star', entryRef: 'rss:e2', syncState: 'synced' })
    render(<OfflineUndoPanel onClose={() => {}} />)
    expect(screen.getByText('未同步（1）')).toBeTruthy()
    expect(screen.getByText('已同步（1）')).toBeTruthy()
    // 撤销未同步条目 → 清单更新
    fireEvent.click(screen.getByRole('button', { name: '撤销 标为已读 rss:e1' }))
    expect(screen.getByText('未同步（0）')).toBeTruthy()
    // 对已同步条目点撤销 → 明确拒绝提示（栈不变）
    fireEvent.click(screen.getByRole('button', { name: '尝试撤销 收藏 rss:e2' }))
    expect(screen.getByText('已同步，不能直接撤销')).toBeTruthy()
    expect(screen.getByText('已同步（1）')).toBeTruthy()
  })

  it('空态诚实；清空按钮一次移除全部', () => {
    recordOfflineUndo({ kind: 'readLater', entryRef: 'rss:e9', syncState: 'synced' })
    render(<OfflineUndoPanel onClose={() => {}} />)
    expect(screen.getByText('没有待撤销的本机操作。离线时失败的批量动作会记在这里。')).toBeTruthy()
    const clear = screen.getByTestId('n359-clear') as HTMLButtonElement
    expect(clear.disabled).toBe(false)
    fireEvent.click(clear)
    expect(screen.getByText(/暂无已同步记录/)).toBeTruthy()
    expect(readOfflineUndoStack()).toEqual([])
    expect((screen.getByTestId('n359-clear') as HTMLButtonElement).disabled).toBe(true)
  })
})
