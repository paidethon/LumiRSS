/** F119 —— 本机草稿（Web 层）。
 *
 * draft-store：白名单注册制（注册表单 debounce 落盘 / 未注册表单零
 * 留存——密码负向）/ LRU20 / 登出清理 / savedAt 判新。
 * NoteFormDialog + AnnotationPopover：恢复条（恢复/放弃/对照），
 * 不自动覆盖当前输入。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { NotesManager } from '../components/NotesManager'
import { AnnotationPopover } from '../components/AnnotationPopover'
import {
  clearAllDrafts,
  clearDraft,
  flushDraftForTests,
  isDraftRegistered,
  loadDraftIfNewer,
  registeredDraftForms,
  saveDraft,
} from '../lib/draft-store'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function renderWithProviders(ui: React.ReactElement): void {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

beforeEach(() => {
  clearAllDrafts()
})

afterEach(() => {
  vi.unstubAllGlobals()
  clearAllDrafts()
})

describe('F119 draft-store 库行为', () => {
  it('F119: 白名单注册表单 debounce 落盘；未注册表单（如密码框）零留存', async () => {
    expect(isDraftRegistered('note-editor')).toBe(true)
    expect(registeredDraftForms().some((form) => /password|secret|api-key/i.test(form))).toBe(false)

    // 未注册的表单（模拟密码/API key 表单）：saveDraft 直接忽略
    saveDraft('password-form', { password: 'hunter2' })
    await new Promise((resolve) => setTimeout(resolve, 2100))
    expect(localStorage.getItem('lumirss-draft-password-form')).toBeNull()
    expect(loadDraftIfNewer('password-form', null)).toBeNull()

    // 注册表单：flush 立即落盘（debounce 计时由 saveDraft 启动）
    flushDraftForTests('note-editor', { title: '未保存标题', contentMd: '正文' })
    const raw = localStorage.getItem('lumirss-draft-note-editor')
    expect(raw).not.toBeNull()
    expect(JSON.parse(raw as string).values.title).toBe('未保存标题')
  })

  it('F119: loadDraftIfNewer 以 savedAt 判新；clearAllDrafts 登出清理', () => {
    const old = new Date(Date.now() - 60_000).toISOString()
    flushDraftForTests('note-editor', { title: 'x' })
    // 手动把 updatedAt 调旧
    localStorage.setItem('lumirss-draft-note-editor', JSON.stringify({ values: { title: 'x' }, updatedAt: old }))
    expect(loadDraftIfNewer('note-editor', new Date().toISOString())).toBeNull()
    expect(loadDraftIfNewer('note-editor', null)?.values.title).toBe('x')

    clearAllDrafts()
    expect(localStorage.getItem('lumirss-draft-note-editor')).toBeNull()
    clearDraft('note-editor') // 幂等
  })
})

describe('F119 笔记编辑草稿恢复条', () => {
  function stubNotes(): void {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation(async (input: RequestInfo | URL) => {
        const url = String(input)
        if (url.endsWith('/library/notes')) return jsonResponse({ items: [] })
        throw new Error(`unexpected ${url}`)
      }),
    )
  }

  it('F119: 有较新草稿 → 恢复条出现；恢复采纳草稿值；对照展示逐字段差异', async () => {
    flushDraftForTests('note-editor', { title: '草稿标题', contentMd: '草稿正文' })
    stubNotes()
    renderWithProviders(<NotesManager />)
    fireEvent.click(await screen.findByRole('button', { name: /新建笔记/ }))

    await waitFor(() => expect(document.querySelector('[data-draft-restore]')).not.toBeNull())
    // 不自动覆盖：输入框仍是空
    expect((screen.getByLabelText('笔记标题') as HTMLInputElement).value).toBe('')

    // 对照：逐字段展示草稿 vs 当前
    fireEvent.click(document.querySelector('[data-draft-diff-toggle]') as HTMLElement)
    const diff = document.querySelector('[data-draft-diff]')
    expect(diff?.textContent).toContain('title')
    expect(diff?.textContent).toContain('草稿标题')

    // 恢复 → 表单采纳草稿值，恢复条消失
    fireEvent.click(document.querySelector('[data-draft-adopt]') as HTMLElement)
    expect((screen.getByLabelText('笔记标题') as HTMLInputElement).value).toBe('草稿标题')
    expect((screen.getByLabelText('笔记正文') as HTMLTextAreaElement).value).toBe('草稿正文')
    expect(document.querySelector('[data-draft-restore]')).toBeNull()
  })

  it('F119: 放弃 → 草稿删除且不再出现恢复条', async () => {
    flushDraftForTests('note-editor', { title: '待放弃', contentMd: '' })
    stubNotes()
    renderWithProviders(<NotesManager />)
    fireEvent.click(await screen.findByRole('button', { name: /新建笔记/ }))
    await waitFor(() => expect(document.querySelector('[data-draft-restore]')).not.toBeNull())
    fireEvent.click(document.querySelector('[data-draft-discard]') as HTMLElement)
    expect(document.querySelector('[data-draft-restore]')).toBeNull()
    expect(localStorage.getItem('lumirss-draft-note-editor')).toBeNull()
  })
})

describe('F119 批注草稿恢复条', () => {
  it('F119: 批注框打开时恢复较新草稿；恢复/放弃行为正确', async () => {
    flushDraftForTests('annotation-editor', { note: '批注草稿内容' })
    const onSave = vi.fn()
    const onCancel = vi.fn()
    render(<AnnotationPopover initialNote="" onSave={onSave} onCancel={onCancel} />)

    await waitFor(() => expect(document.querySelector('[data-draft-restore]')).not.toBeNull())
    expect((screen.getByLabelText('批注备注') as HTMLTextAreaElement).value).toBe('')

    fireEvent.click(document.querySelector('[data-draft-adopt]') as HTMLElement)
    expect((screen.getByLabelText('批注备注') as HTMLTextAreaElement).value).toBe('批注草稿内容')

    // 保存批注 → 草稿清除
    fireEvent.click(screen.getByRole('button', { name: '保存批注' }))
    expect(onSave).toHaveBeenCalledWith('批注草稿内容', 'yellow')
    expect(localStorage.getItem('lumirss-draft-annotation-editor')).toBeNull()
  })
})
