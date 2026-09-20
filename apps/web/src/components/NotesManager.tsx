/** NotesManager — F090 Lumi 笔记全生命周期（BookmarksPage「笔记」页签）。
 *
 * 列表（title/摘要/时间）→ 新建 / 编辑（textarea + 实时 md 预览净化
 * 渲染）→ 保存（编辑带 baseUpdatedAt 乐观锁，409 note_conflict 诚实
 * 报错）→ 删除（软删进回收站，走 /library/trash 恢复）。
 */

import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Pencil, Plus, Trash2 } from 'lucide-react'
import {
  createLumiNote,
  deleteLumiNote,
  getLumiNote,
  listLumiNotes,
  updateLumiNote,
  type LumiNoteDetail,
} from '../api/client'
import { formatTimestamp } from '../lib/date-format'
import { mdPreviewHtml } from '../lib/md-preview'
import { DraftRestoreBar } from './DraftRestoreBar'
import { clearDraft, loadDraftIfNewer, saveDraft, type DraftRecord } from '../lib/draft-store'
import { Button } from './ui/Button'
import { Dialog } from './ui/Dialog'
import { EmptyState } from './ui/EmptyState'
import { IconButton } from './ui/IconButton'
import { Skeleton } from './ui/Skeleton'
import { cx } from './ui/cx'

const inputCls = cx(
  'w-full rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)]',
  'px-3 py-2 text-sm text-[var(--lumi-text-primary)] placeholder:text-[var(--lumi-text-tertiary)]',
  'focus:outline-2 focus:-outline-offset-2 focus:outline-[var(--lumi-focus-ring)]',
)

function NoteFormDialog({ note, onClose }: { note: LumiNoteDetail | null; onClose: () => void }) {
  const [title, setTitle] = useState(note?.title ?? '')
  const [contentMd, setContentMd] = useState(note?.contentMd ?? '')
  const [previewOn, setPreviewOn] = useState(false)
  const queryClient = useQueryClient()
  // F119：本机草稿（白名单 'note-editor'）——挂载时看是否有比已保存
  // 版本更新的草稿；编辑中 debounce 2s 自动保存；提交成功清除。
  const draft = useMemo<DraftRecord | null>(
    () => loadDraftIfNewer('note-editor', note?.updatedAt ?? null),
    // 挂载时一次性判定（草稿不随输入变化重现）
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  )
  const [draftVisible, setDraftVisible] = useState(draft !== null)
  useEffect(() => {
    saveDraft('note-editor', { title, contentMd })
  }, [title, contentMd])
  const save = useMutation({
    mutationFn: () =>
      note === null
        ? createLumiNote({ title: title.trim(), contentMd })
        : updateLumiNote(note.uuid, {
            title: title.trim(),
            contentMd,
            baseUpdatedAt: note.updatedAt,
          }),
    onSuccess: async () => {
      clearDraft('note-editor')
      await queryClient.invalidateQueries({ queryKey: ['lumi-notes'] })
      onClose()
    },
  })
  const canSubmit = title.trim() !== '' && !save.isPending

  return (
    <Dialog
      open
      onClose={onClose}
      title={note === null ? '新建笔记' : '编辑笔记'}
      panelClassName="max-w-2xl"
      footer={
        <div className="flex w-full items-center gap-2">
          <button
            type="button"
            aria-pressed={previewOn}
            onClick={() => setPreviewOn((v) => !v)}
            className="min-h-7 rounded-[var(--lumi-radius-full)] border border-[var(--lumi-border)] px-2.5 py-1 text-xs text-[var(--lumi-text-secondary)] hover:bg-[var(--lumi-surface-hover)]"
          >
            预览
          </button>
          <div className="ml-auto flex items-center gap-2">
            <Button variant="ghost" size="sm" onClick={onClose} disabled={save.isPending}>
              取消
            </Button>
            <Button variant="primary" size="sm" disabled={!canSubmit} onClick={() => save.mutate()}>
              {save.isPending ? '保存中…' : '保存'}
            </Button>
          </div>
        </div>
      }
    >
      <div className="flex flex-col gap-3" data-note-form="">
        {/* F119：恢复条（恢复/放弃/对照）——不自动覆盖当前输入 */}
        {draftVisible && draft !== null ? (
          <DraftRestoreBar
            draft={draft}
            current={{ title, contentMd }}
            onAdopt={() => {
              setTitle(draft.values.title ?? title)
              setContentMd(draft.values.contentMd ?? contentMd)
              clearDraft('note-editor')
              setDraftVisible(false)
            }}
            onDiscard={() => {
              clearDraft('note-editor')
              setDraftVisible(false)
            }}
          />
        ) : null}
        <label className="flex flex-col gap-1">
          <span className="text-xs text-[var(--lumi-text-secondary)]">标题</span>
          <input
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            aria-label="笔记标题"
            className={inputCls}
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-[var(--lumi-text-secondary)]">正文（Markdown，≤100KB）</span>
          <textarea
            value={contentMd}
            onChange={(e) => setContentMd(e.target.value)}
            rows={10}
            aria-label="笔记正文"
            className={cx(inputCls, 'resize-y font-mono')}
          />
        </label>
        {previewOn && (
          <div
            data-note-preview=""
            data-testid="note-preview"
            className="max-h-64 overflow-y-auto rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] p-3 text-sm leading-relaxed text-[var(--lumi-text-primary)] [&_a]:underline [&_blockquote]:border-l-2 [&_blockquote]:pl-2 [&_code]:rounded [&_code]:bg-[var(--lumi-surface-selected)] [&_code]:px-1 [&_h1]:text-lg [&_h1~*]:mt-1 [&_h2]:text-base [&_h3]:text-sm [&_h1]:font-semibold [&_h2]:font-semibold [&_h3]:font-semibold"
            // 净化边界在 lib/md-preview.ts（先转义后渲染 + DOMPurify）。
            dangerouslySetInnerHTML={{ __html: mdPreviewHtml(contentMd) }}
          />
        )}
        {save.isError && (
          <p role="alert" className="text-xs text-[var(--lumi-danger)]">
            {save.error instanceof Error ? save.error.message : '保存失败，请稍后重试。'}
          </p>
        )}
      </div>
    </Dialog>
  )
}

export function NotesManager() {
  const queryClient = useQueryClient()
  const list = useQuery({
    queryKey: ['lumi-notes'],
    queryFn: ({ signal }) => listLumiNotes(null, signal),
  })
  const [editing, setEditing] = useState<LumiNoteDetail | null>(null)
  const [creating, setCreating] = useState(false)
  const [editLoading, setEditLoading] = useState(false)
  const [editError, setEditError] = useState<string | null>(null)

  /** 编辑前先取全量正文（列表只有摘要；避免空正文覆盖）。 */
  async function openEdit(uuid: string) {
    setEditLoading(true)
    setEditError(null)
    try {
      setEditing(await getLumiNote(uuid))
    } catch (error) {
      setEditError(error instanceof Error ? error.message : '加载笔记失败。')
    } finally {
      setEditLoading(false)
    }
  }
  const del = useMutation({
    mutationFn: (uuid: string) => deleteLumiNote(uuid),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['lumi-notes'] })
    },
  })
  const items = list.data?.items ?? []

  return (
    <div className="flex flex-col gap-3" data-notes-manager="">
      <div className="flex items-center gap-2">
        <p className="text-xs text-[var(--lumi-text-secondary)]">
          笔记存于 Lumi 本地库；删除进入回收站可恢复；全文可检索（检索词：笔记标题与正文）。
        </p>
        <div className="ml-auto">
          <Button variant="primary" size="sm" onClick={() => setCreating(true)}>
            <Plus aria-hidden className="size-4" />
            新建笔记
          </Button>
        </div>
      </div>

      {list.isPending && (
        <ul className="flex flex-col gap-2" aria-label="笔记加载中">
          {[0, 1].map((i) => (
            <li key={i}>
              <Skeleton className="h-16 w-full" />
            </li>
          ))}
        </ul>
      )}
      {list.isError && (
        <div role="alert" className="flex flex-col gap-2">
          <EmptyState title="笔记加载失败" description={list.error instanceof Error ? list.error.message : '请稍后重试。'} />
          <div className="flex justify-center">
            <Button variant="secondary" size="sm" onClick={() => list.refetch()}>重试</Button>
          </div>
        </div>
      )}
      {!list.isPending && items.length === 0 && !list.isError && (
        <EmptyState title="还没有笔记" description="点击「新建笔记」开始记录；阅读时的保存笔记也在这里。" />
      )}

      <ul className="flex flex-col gap-2">
        {items.map((note) => (
          <li
            key={note.uuid}
            data-note-uuid={note.uuid}
            className="rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-3"
          >
            <div className="flex items-start gap-2">
              <div className="min-w-0 flex-1">
                <h3 className="text-sm font-medium text-[var(--lumi-text-primary)]">{note.title}</h3>
                <p className="mt-0.5 line-clamp-2 text-xs text-[var(--lumi-text-secondary)]">{note.excerpt}</p>
                <p className="mt-1 text-xs text-[var(--lumi-text-tertiary)]">
                  更新于 {formatTimestamp(note.updatedAt) || '—'}
                </p>
              </div>
              <div className="flex shrink-0 items-center gap-1">
                <IconButton icon={<Pencil aria-hidden className="size-4" />} label="编辑笔记" size="sm" touch
                  onClick={() => void openEdit(note.uuid)}
                />
                <IconButton
                  icon={<Trash2 aria-hidden className="size-4" />}
                  label="删除笔记（进入回收站）"
                  size="sm"
                  touch
                  disabled={del.isPending}
                  onClick={() => del.mutate(note.uuid)}
                />
              </div>
            </div>
          </li>
        ))}
      </ul>
      {del.isError && (
        <p role="alert" className="text-xs text-[var(--lumi-danger)]">
          删除失败：{del.error instanceof Error ? del.error.message : '请稍后重试。'}
        </p>
      )}
      {editLoading && <p className="text-xs text-[var(--lumi-text-tertiary)]">加载笔记…</p>}
      {editError !== null && (
        <p role="alert" className="text-xs text-[var(--lumi-danger)]">{editError}</p>
      )}

      {creating && <NoteFormDialog note={null} onClose={() => setCreating(false)} />}
      {editing !== null && <NoteFormDialog note={editing} onClose={() => setEditing(null)} />}
    </div>
  )
}
