/** BookmarksPage — 书签页（phase2 M1 Library 域）。
 *
 * BFF：/api/v1/library/bookmarks（列表分页 / 幂等创建 / 编辑 / 删除 /
 * Netscape HTML 导入导出）。本页职责：
 * - 头部：导入（原始文件上传，结果 role=status 区含成功/跳过/失败计数
 *   与前几条失败原因）、导出（<a download>，浏览器直下 BFF 附件）、
 *   新建（Dialog：url + 标题 + 备注，POST 幂等）；
 * - 列表：q 防抖 300ms；cursor 分页「加载更多」；行内立即删除
 *   （与时间线诚实语义一致，不做二次确认）与编辑 Dialog（PATCH）；
 * - 诚实状态：加载 Skeleton / 空态 / 错误重试；ApiError 内联展示。
 */

import { useEffect, useMemo, useState } from 'react'
import { Bookmark, Loader2, Pencil, Plus, Search, Trash2, X } from 'lucide-react'
import {
  useBookmarks,
  useCreateBookmarkMutation,
  useDeleteBookmarkMutation,
  useImportBookmarksMutation,
  useUpdateBookmarkMutation,
} from '../../api/queries'
import type { Bookmark as BookmarkItem } from '../../api/types'
import { formatTimestamp } from '../../lib/date-format'
import { safeExternalHttpUrl } from '../../lib/safe-external-http-url'
import { Button } from '../ui/Button'
import { LibraryTrashPanel } from '../LibraryTrashPanel'
import { AnnotationsManager } from '../AnnotationsManager'
import { KnowledgeCardsManager } from '../KnowledgeCardsManager'
import { DuplicatesDialog } from '../DuplicatesDialog'
import { BatchEditDialog } from '../BatchEditDialog'
import { CheckLinksDialog } from '../CheckLinksDialog'
import { MergeDialog, type MergeCandidate } from '../MergeDialog'
import { NotesManager } from '../NotesManager'
import { Dialog } from '../ui/Dialog'
import { EmptyState } from '../ui/EmptyState'
import { IconButton } from '../ui/IconButton'
import { Skeleton } from '../ui/Skeleton'
import { cx } from '../ui/cx'

/** 防抖：输入停止 300ms 后才更新值（与 SearchPage 同一策略）。 */
function useDebouncedValue(value: string, delayMs = 300): string {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs)
    return () => clearTimeout(timer)
  }, [value, delayMs])
  return debounced
}

/** 与 Button secondary/sm 相同视觉的导出链接类（<a> 不能用 Button）。 */
const exportLinkCls = cx(
  'inline-flex items-center justify-center rounded-[var(--lumi-radius-md)] font-medium select-none',
  'bg-[var(--lumi-surface)] text-[var(--lumi-text-primary)] border border-[var(--lumi-border)]',
  'hover:bg-[var(--lumi-surface-hover)] active:bg-[var(--lumi-surface-pressed)]',
  'transition-colors duration-[var(--lumi-motion-fast)]',
  'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
  'min-h-8 px-2.5 text-sm gap-1.5',
)

/** 新建 / 编辑共用表单 Dialog。条件挂载（父级 open && …），字段状态
 * 以 props 一次性初始化；POST/PATCH 失败时 ApiError 内联展示。 */
function BookmarkFormDialog({
  mode,
  bookmark,
  onClose,
}: {
  mode: 'create' | 'edit'
  bookmark: BookmarkItem | null
  onClose: () => void
}) {
  const [url, setUrl] = useState(bookmark?.url ?? '')
  const [title, setTitle] = useState(bookmark?.title ?? '')
  const [note, setNote] = useState(bookmark?.note ?? '')
  const create = useCreateBookmarkMutation()
  const update = useUpdateBookmarkMutation()
  const mutation = mode === 'create' ? create : update
  const pending = mutation.isPending

  const canSubmit =
    title.trim() !== '' && (mode === 'edit' || url.trim() !== '') && !pending

  const submit = () => {
    if (!canSubmit) return
    if (mode === 'create') {
      create.mutate(
        {
          title: title.trim(),
          url: url.trim() || null,
          note: note.trim() || null,
        },
        { onSuccess: onClose },
      )
    } else if (bookmark !== null) {
      update.mutate(
        {
          bookmarkRef: bookmark.ref,
          patch: { title: title.trim(), note: note.trim() },
        },
        { onSuccess: onClose },
      )
    }
  }

  return (
    <Dialog
      open
      onClose={onClose}
      title={mode === 'create' ? '新建书签' : '编辑书签'}
      footer={
        <>
          <Button variant="ghost" size="sm" onClick={onClose} disabled={pending}>
            取消
          </Button>
          <Button variant="primary" size="sm" onClick={submit} disabled={!canSubmit}>
            {pending ? '保存中…' : '保存'}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        {mode === 'create' && (
          <label className="flex flex-col gap-1">
            <span className="text-xs text-[var(--lumi-text-secondary)]">网址</span>
            <input
              type="url"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://…"
              aria-label="书签网址"
              className={cx(
                'w-full rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)]',
                'px-3 py-2 text-sm text-[var(--lumi-text-primary)]',
                'placeholder:text-[var(--lumi-text-tertiary)]',
                'focus:outline-2 focus:-outline-offset-2 focus:outline-[var(--lumi-focus-ring)]',
              )}
            />
          </label>
        )}
        <label className="flex flex-col gap-1">
          <span className="text-xs text-[var(--lumi-text-secondary)]">标题</span>
          <input
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="书签标题"
            aria-label="书签标题"
            className={cx(
              'w-full rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)]',
              'px-3 py-2 text-sm text-[var(--lumi-text-primary)]',
              'placeholder:text-[var(--lumi-text-tertiary)]',
              'focus:outline-2 focus:-outline-offset-2 focus:outline-[var(--lumi-focus-ring)]',
            )}
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-[var(--lumi-text-secondary)]">备注（可选）</span>
          <textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            rows={3}
            aria-label="书签备注"
            className={cx(
              'w-full resize-y rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)]',
              'px-3 py-2 text-sm text-[var(--lumi-text-primary)]',
              'placeholder:text-[var(--lumi-text-tertiary)]',
              'focus:outline-2 focus:-outline-offset-2 focus:outline-[var(--lumi-focus-ring)]',
            )}
          />
        </label>
        {mutation.isError && (
          <p role="alert" className="text-xs text-[var(--lumi-danger)]">
            {mutation.error instanceof Error ? mutation.error.message : '保存失败，请稍后重试。'}
          </p>
        )}
      </div>
    </Dialog>
  )
}

/** 单条书签行：标题外链（仅 url 类型且绝对 http/https）+ url / 备注 /
 * 收藏时间 + 多选（F081/F087）+ 编辑 / 立即删除（无二次确认）。 */
function BookmarkRow({
  bookmark,
  selected,
  onToggleSelect,
}: {
  bookmark: BookmarkItem
  selected: boolean
  onToggleSelect: (ref: string) => void
}) {
  const [editing, setEditing] = useState(false)
  const del = useDeleteBookmarkMutation()
  const safeUrl =
    bookmark.itemType === 'url' ? safeExternalHttpUrl(bookmark.url ?? null) : null

  return (
    <li>
      <article
        data-bookmark-ref={bookmark.ref}
        className="rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-3.5"
      >
        <div className="flex items-start gap-2">
          <input
            type="checkbox"
            checked={selected}
            onChange={() => onToggleSelect(bookmark.ref)}
            aria-label={`选择书签：${bookmark.title}`}
            className="mt-1 size-4 shrink-0 accent-[var(--lumi-accent)]"
          />
          <div className="min-w-0 flex-1">
            {safeUrl !== null ? (
              <a
                href={safeUrl}
                target="_blank"
                rel="noreferrer noopener"
                className="text-sm font-medium text-[var(--lumi-text-primary)] underline-offset-2 transition-colors duration-[var(--lumi-motion-fast)] hover:text-[var(--lumi-accent-text)] hover:underline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
              >
                {bookmark.title}
              </a>
            ) : (
              <h3 className="text-sm font-medium text-[var(--lumi-text-primary)]">
                {bookmark.title}
              </h3>
            )}
            {bookmark.url != null && bookmark.url !== '' && (
              <p className="mt-0.5 truncate text-xs text-[var(--lumi-text-tertiary)]">
                {bookmark.url}
              </p>
            )}
            {bookmark.note !== '' && (
              <p className="mt-1 whitespace-pre-wrap text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
                {bookmark.note}
              </p>
            )}
            <p className="mt-1 text-xs text-[var(--lumi-text-tertiary)]">
              {formatTimestamp(bookmark.createdAt) || '—'}
            </p>
            {del.isError && (
              <p role="alert" className="mt-1 text-xs text-[var(--lumi-danger)]">
                删除失败：{del.error instanceof Error ? del.error.message : '请稍后重试。'}
              </p>
            )}
          </div>
          <div className="flex shrink-0 items-center gap-1">
            <IconButton
              icon={<Pencil aria-hidden className="size-4" />}
              label="编辑书签"
              size="sm"
              touch
              onClick={() => setEditing(true)}
            />
            <IconButton
              icon={
                del.isPending ? (
                  <Loader2 aria-hidden className="size-4 animate-spin" />
                ) : (
                  <Trash2 aria-hidden className="size-4" />
                )
              }
              label="删除书签"
              size="sm"
              touch
              disabled={del.isPending}
              onClick={() => del.mutate(bookmark.ref)}
            />
          </div>
        </div>
      </article>
      {editing && (
        <BookmarkFormDialog mode="edit" bookmark={bookmark} onClose={() => setEditing(false)} />
      )}
    </li>
  )
}

export default function BookmarksPage() {
  const [input, setInput] = useState('')
  const debounced = useDebouncedValue(input)
  const q = debounced.trim()

  const list = useBookmarks(q)
  const importMutation = useImportBookmarksMutation()
  const { data, isPending, isError, error, refetch, hasNextPage, isFetchingNextPage, fetchNextPage } =
    list

  const bookmarks = useMemo(
    () => data?.pages.flatMap((page) => page.items) ?? [],
    [data],
  )
  const hasQuery = q !== ''
  // F019：回收站面板开关
  const [trashOpen, setTrashOpen] = useState(false)
  // F051：批注页签（书签/批注双页签；管理器组件承载检索与复习队列）
  // F070：四页签（书签/批注/知识卡片/笔记）。
  const [pageTab, setPageTab] = useState<'bookmarks' | 'annotations' | 'knowledge' | 'notes'>('bookmarks')
  // F071：疑似重复审核对话框。F082：合并对话框。
  const [duplicatesOpen, setDuplicatesOpen] = useState(false)
  const [mergeOpen, setMergeOpen] = useState(false)
  // F081/F087：多选批量操作。
  const [selectedRefs, setSelectedRefs] = useState<Set<string>>(new Set())
  const [batchEditOpen, setBatchEditOpen] = useState(false)
  const [checkLinksOpen, setCheckLinksOpen] = useState(false)

  function toggleSelect(ref: string) {
    setSelectedRefs((prev) => {
      const next = new Set(prev)
      if (next.has(ref)) next.delete(ref)
      else next.add(ref)
      return next
    })
  }

  if (pageTab === 'knowledge') {
    return (
      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto p-3 max-lg:pb-[76px]">
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <h1 className="text-base font-semibold text-[var(--lumi-text-primary)]">知识卡片</h1>
          <div className="flex items-center gap-1.5" role="group" aria-label="页签">
            <Button size="sm" variant="ghost" onClick={() => setPageTab('bookmarks')}>
              书签
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setPageTab('annotations')}>
              批注
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setPageTab('notes')}>
              笔记
            </Button>
            <Button size="sm" variant="primary">知识卡片</Button>
          </div>
        </div>
        <KnowledgeCardsManager />
      </div>
    )
  }

  if (pageTab === 'annotations') {
    return (
      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto p-3 max-lg:pb-[76px]">
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <div className="flex items-center gap-1.5" role="group" aria-label="页签">
            <Button size="sm" variant="ghost" onClick={() => setPageTab('bookmarks')}>
              书签
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setPageTab('bookmarks')}>
              批注
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setPageTab('notes')}>
              笔记
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setPageTab('knowledge')}>
              知识卡片
            </Button>
          </div>
        </div>
        <AnnotationsManager />
      </div>
    )
  }

  if (pageTab === 'notes') {
    return (
      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto p-3 max-lg:pb-[76px]">
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <h1 className="text-base font-semibold text-[var(--lumi-text-primary)]">笔记</h1>
          <div className="flex items-center gap-1.5" role="group" aria-label="页签">
            <Button size="sm" variant="ghost" onClick={() => setPageTab('bookmarks')}>
              书签
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setPageTab('annotations')}>
              批注
            </Button>
            <Button size="sm" variant="primary">笔记</Button>
            <Button size="sm" variant="ghost" onClick={() => setPageTab('knowledge')}>
              知识卡片
            </Button>
          </div>
        </div>
        <NotesManager />
      </div>
    )
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <DuplicatesDialog open={duplicatesOpen} onClose={() => setDuplicatesOpen(false)} />
      {batchEditOpen && selectedRefs.size > 0 && (
        <BatchEditDialog refs={[...selectedRefs]} onClose={() => { setBatchEditOpen(false); setSelectedRefs(new Set()) }} />
      )}
      {checkLinksOpen && selectedRefs.size > 0 && (
        <CheckLinksDialog refs={[...selectedRefs]} onClose={() => { setCheckLinksOpen(false); setSelectedRefs(new Set()) }} />
      )}
      {mergeOpen && (
        <MergeDialog
          items={bookmarks.map((b): MergeCandidate => ({ ref: b.ref, title: b.title }))}
          onClose={() => setMergeOpen(false)}
        />
      )}
      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto p-3 max-lg:pb-[76px]">
        {/* 头部：标题 + 页签 + 导入 / 导出 / 新建 */}
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-base font-semibold text-[var(--lumi-text-primary)]">书签</h1>
          <Button size="sm" variant="ghost" onClick={() => setPageTab('annotations')}>
            批注
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setPageTab('knowledge')}>
            知识卡片
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setDuplicatesOpen(true)}>
            整理
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setMergeOpen(true)}>
            合并
          </Button>
          {selectedRefs.size > 0 && (
            <>
              <span data-selection-count="" className="text-xs text-[var(--lumi-text-secondary)]">
                已选 {selectedRefs.size} 条
              </span>
              <Button size="sm" variant="secondary" onClick={() => setBatchEditOpen(true)}>
                批量编辑
              </Button>
              <Button size="sm" variant="secondary" onClick={() => setCheckLinksOpen(true)}>
                检查链接
              </Button>
            </>
          )}
          <div className="ml-auto flex items-center gap-1.5">
            {/* 导入：原始 Netscape HTML 文件上传（BFF 解析）。sr-only input
                保持可聚焦（键盘可操作）；label 承载视觉按钮。 */}
            <input
              id="bookmark-import-input"
              type="file"
              accept=".html,.htm"
              aria-label="导入书签文件"
              disabled={importMutation.isPending}
              className="sr-only"
              onChange={(e) => {
                const file = e.target.files?.[0]
                if (file) importMutation.mutate(file)
                e.target.value = ''
              }}
            />
            <label
              htmlFor="bookmark-import-input"
              className={cx(
                exportLinkCls,
                'cursor-pointer',
                importMutation.isPending && 'pointer-events-none opacity-50',
              )}
            >
              {importMutation.isPending ? (
                <Loader2 aria-hidden className="size-4 animate-spin" />
              ) : null}
              导入
            </label>
            <a
              href="/api/v1/library/bookmarks/export.html"
              download
              className={exportLinkCls}
            >
              导出
            </a>
            <button
              type="button"
              aria-pressed={trashOpen}
              onClick={() => setTrashOpen((v) => !v)}
              className="min-h-7 rounded-[var(--lumi-radius-full)] border border-[var(--lumi-border)] px-2.5 py-1 text-xs text-[var(--lumi-text-secondary)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)]"
            >
              回收站
            </button>
            <NewBookmarkButton />
          </div>
        </div>

        {/* F019：回收站面板 */}
        {trashOpen && <LibraryTrashPanel />}
        {/* 导入结果 / 错误（诚实计数 + 前几条失败原因） */}
        {importMutation.isError && (
          <div role="alert" className="mt-2 text-sm text-[var(--lumi-danger)]">
            导入失败：{importMutation.error instanceof Error ? importMutation.error.message : '请稍后重试。'}
          </div>
        )}
        {importMutation.data != null && (
          <div
            role="status"
            className="mt-2 flex items-start gap-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-3 text-sm"
          >
            <div className="min-w-0 flex-1">
              <p className="text-[var(--lumi-text-primary)]">
                导入完成：成功 {importMutation.data.imported} 条，跳过 {importMutation.data.skipped} 条
                {importMutation.data.failed.length > 0
                  ? `，失败 ${importMutation.data.failed.length} 条`
                  : ''}
              </p>
              {importMutation.data.failed.length > 0 && (
                <ul className="mt-1.5 flex flex-col gap-0.5 text-xs text-[var(--lumi-text-secondary)]">
                  {importMutation.data.failed.slice(0, 3).map((f) => (
                    <li key={`${f.index}-${f.url}`}>
                      第 {f.index + 1} 条（{f.url}）：{f.reason}
                    </li>
                  ))}
                  {importMutation.data.failed.length > 3 && (
                    <li>… 以及另外 {importMutation.data.failed.length - 3} 条失败</li>
                  )}
                </ul>
              )}
            </div>
            <IconButton
              icon={<X aria-hidden className="size-4" />}
              label="关闭导入结果"
              size="sm"
              onClick={() => importMutation.reset()}
            />
          </div>
        )}

        {/* 搜索（防抖 → q 参数） */}
        <div className="relative mt-2.5">
          <Search
            aria-hidden
            className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-[var(--lumi-text-tertiary)]"
          />
          <input
            type="search"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="搜索书签标题或备注…"
            aria-label="搜索书签"
            className={cx(
              'w-full rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)]',
              'py-2.5 pl-9 pr-3 text-sm text-[var(--lumi-text-primary)]',
              'placeholder:text-[var(--lumi-text-tertiary)]',
              'focus:outline-2 focus:-outline-offset-2 focus:outline-[var(--lumi-focus-ring)]',
            )}
          />
        </div>

        {/* 列表 / 诚实状态 */}
        {isPending ? (
          <ul className="mt-3 flex flex-col gap-2" aria-label="书签加载中">
            {Array.from({ length: 4 }, (_, i) => (
              <li key={i}>
                <Skeleton className="h-20 w-full" />
              </li>
            ))}
          </ul>
        ) : isError ? (
          <div className="mt-6" role="alert">
            <EmptyState
              icon={<Bookmark aria-hidden className="size-8" />}
              title="书签加载失败"
              description={error instanceof Error ? error.message : '请稍后重试。'}
            />
            <div className="flex justify-center">
              <Button variant="secondary" size="sm" onClick={() => refetch()}>
                重试
              </Button>
            </div>
          </div>
        ) : bookmarks.length === 0 ? (
          <div className="mt-8">
            {hasQuery ? (
              <EmptyState
                icon={<Search aria-hidden className="size-8" />}
                title="没有匹配的书签"
                description="换个关键词试试。"
              />
            ) : (
              <EmptyState
                icon={<Bookmark aria-hidden className="size-8" />}
                title="无书签"
                description='点击右上角「新建」添加，或在阅读时点「存书签」。'
              />
            )}
          </div>
        ) : (
          <>
            <ul className="mt-3 flex flex-col gap-2" aria-label="书签列表">
              {bookmarks.map((bookmark) => (
                <BookmarkRow
                  key={bookmark.ref}
                  bookmark={bookmark}
                  selected={selectedRefs.has(bookmark.ref)}
                  onToggleSelect={toggleSelect}
                />
              ))}
            </ul>
            {hasNextPage && (
              <div className="mt-3 flex justify-center">
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => fetchNextPage()}
                  disabled={isFetchingNextPage}
                >
                  {isFetchingNextPage ? '加载中…' : '加载更多'}
                </Button>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}

/** 新建书签按钮 + Dialog（条件挂载在页级，保证单实例）。 */
function NewBookmarkButton() {
  const [open, setOpen] = useState(false)
  return (
    <>
      <Button variant="primary" size="sm" onClick={() => setOpen(true)}>
        <Plus aria-hidden className="size-4" />
        新建
      </Button>
      {open && (
        <BookmarkFormDialog mode="create" bookmark={null} onClose={() => setOpen(false)} />
      )}
    </>
  )
}
