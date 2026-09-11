/** ObsidianPage — phase2 G6：Obsidian 库（只读投影）。
 *
 * App 已把本页接入 section='obsidian'（桌面 Timeline 列位 + 移动 section 区）。
 *
 * - 未配置（status.vaultPath 为空）：Vault 路径输入 + 连接（PUT settings；
 *   503 vault_unreachable / 403 vault_permission_denied 的 message 原样透出）。
 * - 已配置：状态行（笔记数 / 上次扫描相对时间 / lastError 用 danger token
 *   诚实展示）+ 重扫（POST rescan，报告「新增 X · 更改 Y · 删除 Z ·
 *   改名 N · 跳过 S」）+ 搜索（300ms 防抖 → GET notes）+ 笔记列表。
 * - 笔记详情 Dialog：contentHtml 是服务端 markdown 渲染的【不可信】HTML，
 *   渲染前必须过 lib/sanitize-article-html.ts（全站唯一 DOMPurify 边界）；
 *   「在 Obsidian 中打开」仅在 vaultPath 已知时渲染，
 *   href = obsidian://open?path=encodeURIComponent(vaultPath + '/' + relPath)。
 *
 * 所有 HTTP 经 src/api/client.ts；loading / empty / error 三态齐备。 */

import { useEffect, useState } from 'react'
import {
  AlertCircle,
  BookOpenText,
  ExternalLink,
  RefreshCw,
  Search,
} from 'lucide-react'
import {
  useConnectObsidianMutation,
  useObsidianNoteDetail,
  useObsidianNotes,
  useObsidianRescanMutation,
  useObsidianStatus,
} from '../../api/queries'
import type { NoteView, ObsidianStatus } from '../../api/client'
import { dateTimeFormatter } from '../../lib/date-format'
import { sanitizeArticleHtml } from '../../lib/sanitize-article-html'
import { Button } from '../ui/Button'
import { Dialog } from '../ui/Dialog'
import { EmptyState } from '../ui/EmptyState'
import { Skeleton } from '../ui/Skeleton'
import { cx } from '../ui/cx'

const inputCls = cx(
  'w-full rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2.5 min-h-9 text-sm',
  'text-[var(--lumi-text-primary)] placeholder:text-[var(--lumi-text-tertiary)]',
  'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
  'disabled:cursor-not-allowed disabled:opacity-50',
)

/** 防抖：输入停止 300ms 后才更新值（与 SearchPage 同一策略）。 */
function useDebouncedValue(value: string, delayMs = 300): string {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs)
    return () => clearTimeout(timer)
  }, [value, delayMs])
  return debounced
}

/** ISO 时间戳 → 相对时间；无效 / 缺失回退绝对时间或「从未」。 */
function formatRelative(iso: string | null | undefined): string {
  if (iso === null || iso === undefined || iso === '') return '从未'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '从未'
  const minutes = Math.floor((Date.now() - date.getTime()) / 60_000)
  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes} 分钟前`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} 小时前`
  const days = Math.floor(hours / 24)
  if (days < 30) return `${days} 天前`
  return dateTimeFormatter.format(date)
}

/** 未配置：连接 Vault。 */
function ConnectView() {
  const connect = useConnectObsidianMutation()
  const [vaultPath, setVaultPath] = useState('')

  const connectVault = () => {
    connect.mutate(vaultPath.trim())
  }

  return (
    <div className="flex flex-1 items-center justify-center p-4">
      <div className="w-full max-w-sm rounded-[var(--lumi-radius-xl)] border border-[var(--lumi-border)] p-5">
        <div className="flex items-center gap-2">
          <BookOpenText aria-hidden className="size-5 text-[var(--lumi-text-tertiary)]" />
          <h2 className="text-base font-semibold text-[var(--lumi-text-primary)]">Obsidian 库</h2>
        </div>
        <p className="mt-2 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
          输入服务器本机上的 Vault 目录绝对路径建立只读索引；Lumi 只读文件，绝不改动你的笔记。
        </p>
        <label
          htmlFor="obsidian-vault-path"
          className="mt-4 block text-xs font-medium text-[var(--lumi-text-primary)]"
        >
          Vault 路径
        </label>
        <input
          id="obsidian-vault-path"
          value={vaultPath}
          onChange={(e) => setVaultPath(e.target.value)}
          placeholder="/home/me/Documents/MyVault"
          aria-label="Vault 路径"
          className={cx(inputCls, 'mt-1')}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && vaultPath.trim() !== '' && !connect.isPending) {
              connectVault()
            }
          }}
        />
        <Button
          size="sm"
          variant="primary"
          className="mt-3"
          onClick={connectVault}
          disabled={vaultPath.trim() === '' || connect.isPending}
        >
          {connect.isPending ? '连接中…' : '连接'}
        </Button>
        {connect.isError && (
          <p
            role="alert"
            className="mt-3 flex items-start gap-1.5 text-xs leading-relaxed text-[var(--lumi-danger)]"
          >
            <AlertCircle aria-hidden className="mt-0.5 size-3.5 shrink-0" />
            {connect.error.message}
          </p>
        )}
      </div>
    </div>
  )
}

/** 笔记详情 Dialog：contentHtml 先 sanitize 再渲染（不可信输入）。 */
function NoteDetailDialog({
  note,
  vaultPath,
  onClose,
}: {
  note: NoteView | null
  vaultPath: string
  onClose: () => void
}) {
  const detail = useObsidianNoteDetail(note?.ref ?? null)
  const resolved = detail.data ?? note
  const contentHtml = resolved?.contentHtml ?? null
  const obsidianUrl =
    vaultPath !== '' && resolved !== undefined && resolved !== null
      ? `obsidian://open?path=${encodeURIComponent(`${vaultPath}/${resolved.relPath}`)}`
      : null

  return (
    <Dialog
      open={note !== null}
      onClose={onClose}
      title={resolved?.title ?? '笔记'}
      panelClassName="max-w-2xl"
      footer={
        <>
          {obsidianUrl !== null && (
            <a
              href={obsidianUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="mr-auto inline-flex items-center gap-1 text-sm text-[var(--lumi-accent-text)] hover:underline"
            >
              在 Obsidian 中打开
              <ExternalLink aria-hidden className="size-3.5" />
            </a>
          )}
          <Button variant="ghost" size="sm" onClick={onClose}>
            关闭
          </Button>
        </>
      }
    >
      {detail.isError ? (
        <p role="alert" className="text-sm text-[var(--lumi-danger)]">
          {detail.error.message}
        </p>
      ) : detail.isPending && resolved === undefined ? (
        <div className="flex flex-col gap-2" aria-label="笔记加载中">
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-4/5" />
          <Skeleton className="h-4 w-3/5" />
        </div>
      ) : resolved !== undefined && resolved !== null ? (
        <div className="flex flex-col gap-3">
          <p className="text-xs text-[var(--lumi-text-tertiary)]">{resolved.relPath}</p>
          {resolved.tags.length > 0 && (
            <ul className="flex flex-wrap gap-1.5" aria-label="标签">
              {resolved.tags.map((tag) => (
                <li
                  key={tag}
                  className="rounded-[var(--lumi-radius-full)] border border-[var(--lumi-border)] px-2 py-0.5 text-xs text-[var(--lumi-text-secondary)]"
                >
                  {tag}
                </li>
              ))}
            </ul>
          )}
          {contentHtml !== null && contentHtml !== '' ? (
            <div
              className="lumi-article-body"
              // 安全边界：contentHtml 经 sanitizeArticleHtml（DOMPurify）清洗。
              dangerouslySetInnerHTML={{ __html: sanitizeArticleHtml(contentHtml) }}
            />
          ) : (
            <p className="text-xs text-[var(--lumi-text-tertiary)]">笔记内容为空。</p>
          )}
        </div>
      ) : null}
    </Dialog>
  )
}

/** 已配置：状态 + 重扫 + 搜索 + 笔记列表。 */
function ConfiguredView({ status }: { status: ObsidianStatus }) {
  const rescan = useObsidianRescanMutation()
  const [input, setInput] = useState('')
  const [openRef, setOpenRef] = useState<string | null>(null)
  const q = useDebouncedValue(input)
  const notes = useObsidianNotes(q)

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto p-3 max-lg:pb-[76px]">
        {/* 状态行：笔记数 / 上次扫描 / lastError（诚实展示） */}
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-1">
          <h2 className="text-sm font-semibold text-[var(--lumi-text-primary)]">Obsidian 库</h2>
          <span className="text-xs text-[var(--lumi-text-tertiary)]" role="status">
            {status.noteCount} 条笔记 · 上次扫描：{formatRelative(status.lastScanAt)}
          </span>
          <Button
            size="sm"
            variant="secondary"
            className="ml-auto shrink-0"
            onClick={() => rescan.mutate()}
            disabled={rescan.isPending}
          >
            <RefreshCw aria-hidden className={cx('size-3.5', rescan.isPending && 'animate-spin')} />
            {rescan.isPending ? '扫描中…' : '重扫'}
          </Button>
        </div>
        {status.lastError !== null && status.lastError !== undefined && status.lastError !== '' && (
          <p
            role="alert"
            className="mt-2 flex items-start gap-1.5 px-1 text-xs leading-relaxed text-[var(--lumi-danger)]"
          >
            <AlertCircle aria-hidden className="mt-0.5 size-3.5 shrink-0" />
            上次扫描出错：{status.lastError}
          </p>
        )}
        {rescan.isError && (
          <p role="alert" className="mt-2 flex items-start gap-1.5 px-1 text-xs leading-relaxed text-[var(--lumi-danger)]">
            <AlertCircle aria-hidden className="mt-0.5 size-3.5 shrink-0" />
            {rescan.error.message}
          </p>
        )}
        {rescan.data !== undefined && (
          <p role="status" className="mt-2 px-1 text-xs text-[var(--lumi-text-secondary)]">
            新增 {rescan.data.added} · 更改 {rescan.data.changed} · 删除 {rescan.data.removed} · 改名{' '}
            {rescan.data.renames} · 跳过 {rescan.data.skipped}
          </p>
        )}

        {/* 搜索（防抖；Enter 立即） */}
        <div className="relative mt-3">
          <Search
            aria-hidden
            className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-[var(--lumi-text-tertiary)]"
          />
          <input
            type="search"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="搜索笔记标题与内容…"
            aria-label="搜索笔记"
            className={cx(inputCls, 'min-h-10 pl-9')}
          />
        </div>

        {/* 笔记列表：loading / empty / error */}
        {notes.isPending ? (
          <ul className="mt-3 flex flex-col gap-2" aria-label="笔记加载中">
            {[0, 1, 2].map((i) => (
              <li key={i}>
                <Skeleton className="h-14 w-full" />
              </li>
            ))}
          </ul>
        ) : notes.isError ? (
          <div className="mt-6" role="alert">
            <EmptyState
              icon={<AlertCircle aria-hidden className="size-8" />}
              title="笔记列表加载失败"
              description={notes.error.message}
              action={
                <Button size="sm" variant="secondary" onClick={() => notes.refetch()}>
                  重试
                </Button>
              }
            />
          </div>
        ) : notes.data.items.length === 0 ? (
          <div className="mt-6">
            <EmptyState
              icon={<BookOpenText aria-hidden className="size-8" />}
              title={q.trim() === '' ? '还没有笔记' : `没有匹配「${q.trim()}」的笔记`}
              description={
                q.trim() === ''
                  ? '确认 Vault 里已有 .md 文件，或点上方「重扫」重建索引。'
                  : '试试更短的关键词。'
              }
            />
          </div>
        ) : (
          <ul className="mt-3 flex flex-col gap-1.5" aria-label="笔记列表">
            {notes.data.items.map((note) => (
              <li key={note.ref}>
                <button
                  type="button"
                  onClick={() => setOpenRef(note.ref)}
                  className={cx(
                    'flex w-full flex-col gap-1 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] px-3 py-2.5 text-left',
                    'transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)]',
                    'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
                  )}
                >
                  <span className="truncate text-sm font-medium text-[var(--lumi-text-primary)]">
                    {note.title}
                  </span>
                  <span className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-xs text-[var(--lumi-text-tertiary)]">
                    <span className="truncate">{note.relPath}</span>
                    <span>索引于 {formatRelative(note.indexedAt)}</span>
                    {note.tags.map((tag) => (
                      <span
                        key={tag}
                        className="rounded-[var(--lumi-radius-full)] border border-[var(--lumi-border)] px-1.5 py-0.5 text-[11px] text-[var(--lumi-text-secondary)]"
                      >
                        {tag}
                      </span>
                    ))}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <NoteDetailDialog
        note={openRef === null ? null : (notes.data?.items.find((n) => n.ref === openRef) ?? null)}
        vaultPath={status.vaultPath}
        onClose={() => setOpenRef(null)}
      />
    </div>
  )
}

export default function ObsidianPage() {
  const status = useObsidianStatus()

  if (status.isPending) {
    return (
      <div className="flex flex-1 flex-col gap-3 p-4" aria-label="Obsidian 状态加载中">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="flex flex-col gap-1.5">
            <Skeleton className="h-3 w-2/5" />
            <Skeleton className="h-4 w-4/5" />
          </div>
        ))}
      </div>
    )
  }

  if (status.isError) {
    return (
      <div className="p-4 text-sm text-[var(--lumi-danger)]" role="alert">
        <p>Obsidian 状态加载失败</p>
        <p className="mt-1 text-xs text-[var(--lumi-text-secondary)]">{status.error.message}</p>
        <Button size="sm" onClick={() => status.refetch()} className="mt-2">
          重试
        </Button>
      </div>
    )
  }

  const data = status.data
  if (data === undefined) {
    return null
  }

  // 未配置 = vaultPath 为空（BFF 契约：未连接 Vault 时报告空路径）。
  return data.vaultPath !== '' ? <ConfiguredView status={data} /> : <ConnectView />
}
