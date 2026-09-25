/** RagW5Panels — W5 RAG 三个设置面板。
 *
 * - RagExclusionsPanel（F091）：逐来源「纳入索引 / 排除」开关 + 受影响
 *   分块计数预览。AI 禁用（F066）优先于本开关——ai_disabled 来源即使
 *   未排除也不进索引（面板如实标注两者区别）。
 * - RagTrySearchPanel（F092）：真实 /rag/search 试检索；分数后端没给
 *   就显示「—」，绝不编造百分比；来源点击 resolve→打开由 EntryRefLink
 *   语义交给 Reader（此处渲染可点击 ref 行触发 onOpen）。
 * - RagConsistencyPanel（F100）：版本失配扫描（content_hash /
 *   embedding_model）+ 有界修复；无失配诚实空态。
 */

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  getRagCoverage,
  listRagExclusions,
  listRagInconsistencies,
  ragChunkPreview,
  ragTrySearch,
  repairRagRefs,
  setRagExclusion,
  type RagChunkPreview,
  type RagCoverage,
  type RagExclusionItem,
} from '../api/client'
import { Button } from './ui/Button'
import { Dialog } from './ui/Dialog'
import { Skeleton } from './ui/Skeleton'
import { resolveAndOpen } from '../lib/open-item'
import { cx } from './ui/cx'

// ---- F091 -------------------------------------------------------------------

export function RagExclusionsPanel() {
  const list = useQuery({
    queryKey: ['rag-exclusions'],
    queryFn: ({ signal }) => listRagExclusions(signal),
  })
  const queryClient = useQueryClient()
  const toggle = useMutation({
    mutationFn: ({ feedRef, excluded }: { feedRef: string; excluded: boolean }) =>
      setRagExclusion(feedRef, excluded),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['rag-exclusions'] })
      await queryClient.invalidateQueries({ queryKey: ['rag-status'] })
    },
  })
  const items: RagExclusionItem[] = list.data?.items ?? []

  return (
    <div className="flex flex-col gap-2" data-rag-exclusions="">
      <p className="text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
        索引范围：排除的来源不进入语义索引（现有分块即时失效）。与「AI 禁用」
        相互独立——AI 禁用优先级更高：被禁用来源即使此处未排除也不进索引，
        也不出现在 Agent 结果里。
      </p>
      {list.isPending && <Skeleton className="h-20 w-full" />}
      {list.isError && (
        <p role="alert" className="text-xs text-[var(--lumi-danger)]">
          排除列表加载失败：{list.error instanceof Error ? list.error.message : '请稍后重试。'}
        </p>
      )}
      {!list.isPending && items.length === 0 && !list.isError && (
        <p className="text-xs text-[var(--lumi-text-tertiary)]">暂无已知来源。</p>
      )}
      <ul className="flex flex-col gap-1.5">
        {items.map((item) => (
          <li
            key={item.feedUrl}
            data-exclusion-feed={item.feedUrl}
            className="flex items-center gap-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2.5 py-1.5 text-xs"
          >
            <label className="flex min-w-0 flex-1 items-center gap-2">
              <input
                type="checkbox"
                checked={!item.ragExcluded}
                disabled={toggle.isPending}
                onChange={() => toggle.mutate({ feedRef: item.feedUrl, excluded: !item.ragExcluded })}
                aria-label={`纳入索引：${item.feedUrl}`}
              />
              <span className="min-w-0 flex-1 truncate text-[var(--lumi-text-primary)]">{item.feedUrl}</span>
            </label>
            {item.aiDisabled && (
              <span className="shrink-0 rounded-full bg-[var(--lumi-surface-selected)] px-1.5 py-0.5 text-[10px] text-[var(--lumi-text-secondary)]">
                AI 已禁用（优先排除）
              </span>
            )}
            <span className="shrink-0 text-[var(--lumi-text-tertiary)]" title="排除将移除的现有分块数">
              {item.affectedChunks} 块
            </span>
          </li>
        ))}
      </ul>
      {toggle.isError && (
        <p role="alert" className="text-xs text-[var(--lumi-danger)]">
          {toggle.error instanceof Error ? toggle.error.message : '更新失败，请稍后重试。'}
        </p>
      )}
    </div>
  )
}

// ---- F092 -------------------------------------------------------------------

export function RagTrySearchPanel({ enabled }: { enabled: boolean }) {
  const [query, setQuery] = useState('')
  const [result, setResult] = useState<Awaited<ReturnType<typeof ragTrySearch>> | null>(null)
  const search = useMutation({
    mutationFn: () => ragTrySearch(query.trim()),
    onSuccess: setResult,
  })

  if (!enabled) {
    return (
      <p className="text-xs text-[var(--lumi-text-tertiary)]" data-try-search-disabled="">
        语义检索未启用：先在上方启用并重建索引后，才能试检索。
      </p>
    )
  }
  return (
    <div className="flex flex-col gap-2" data-rag-try-search="">
      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault()
          if (query.trim() !== '') search.mutate()
        }}
      >
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="试检索查询…"
          aria-label="试检索查询"
          className="flex-1 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-3 py-1.5 text-sm text-[var(--lumi-text-primary)]"
        />
        <Button type="submit" variant="secondary" size="sm" disabled={search.isPending}>
          {search.isPending ? '检索中…' : '检索'}
        </Button>
      </form>
      {search.isError && (
        <p role="alert" className="text-xs text-[var(--lumi-danger)]">
          {search.error instanceof Error ? search.error.message : '检索失败，请稍后重试。'}
        </p>
      )}
      {result !== null && (
        <div className="flex flex-col gap-1.5" data-try-results="">
          {result.items.length === 0 && (
            <p className="text-xs text-[var(--lumi-text-tertiary)]">没有命中的分块。</p>
          )}
          {result.items.map((item) => (
            <div
              key={`${item.ref}:${item.text.slice(0, 12)}`}
              data-try-hit={item.ref}
              className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2.5 py-1.5 text-xs"
            >
              <div className="flex items-center gap-2">
                {/* 点击命中行 → resolve → 打开阅读器（失效目标不打开，诚实降级）。 */}
                <button
                  type="button"
                  data-try-hit-open={item.ref}
                  onClick={() => void resolveAndOpen(item.ref)}
                  className="min-w-0 flex-1 truncate text-left font-medium text-[var(--lumi-text-primary)] underline-offset-2 transition-colors duration-[var(--lumi-motion-fast)] hover:text-[var(--lumi-accent-text)] hover:underline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
                >
                  {item.title ?? item.ref}
                </button>
                <span className="shrink-0 text-[var(--lumi-text-tertiary)]">
                  {/* 分数缺失显示「—」——绝不编造百分比。 */}
                  分数 {typeof item.score === 'number' ? item.score.toFixed(3) : '—'}
                </span>
              </div>
              <p className="mt-0.5 line-clamp-2 text-[var(--lumi-text-secondary)]">{item.text}</p>
            </div>
          ))}
          {result.semanticError != null && (
            <p role="alert" className="text-xs text-[var(--lumi-danger)]">{result.semanticError}</p>
          )}
        </div>
      )}
    </div>
  )
}

// ---- N152 索引覆盖率 ----------------------------------------------------------

/** N152 覆盖率卡片：语料 ↔ 索引真实分桶（indexable/indexed/stale/failed
 * 来自行与作业，unsupported 按 kind 给原因）。纯只读盘点。 */
export function RagCoveragePanel() {
  const scan = useMutation({
    mutationFn: () => getRagCoverage(),
  })
  const coverage: RagCoverage | undefined = scan.data

  return (
    <div className="flex flex-col gap-2" data-rag-coverage="">
      <div className="flex items-center gap-2">
        <Button variant="secondary" size="sm" disabled={scan.isPending} onClick={() => scan.mutate()}>
          {scan.isPending ? '盘点中…' : '扫描索引覆盖率'}
        </Button>
        {coverage !== undefined && (
          <span className="text-xs text-[var(--lumi-text-secondary)]">
            可索引 {coverage.indexable} · 已索引 {coverage.indexed} · 过期 {coverage.stale} · 失败{' '}
            {coverage.failed} · 不支持 {coverage.unsupported.count}
          </span>
        )}
      </div>
      {scan.isError && (
        <p role="alert" className="text-xs text-[var(--lumi-danger)]">
          覆盖率盘点失败：{scan.error instanceof Error ? scan.error.message : '请稍后重试。'}
        </p>
      )}
      {coverage !== undefined && (
        <>
          <dl className="grid grid-cols-4 gap-2 text-xs max-sm:grid-cols-2">
            {(
              [
                ['可索引', coverage.indexable],
                ['已索引', coverage.indexed],
                ['过期', coverage.stale],
                ['失败', coverage.failed],
              ] as const
            ).map(([label, value]) => (
              <div
                key={label}
                data-coverage-bucket={label}
                className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2 py-1.5"
              >
                <dt className="text-[var(--lumi-text-tertiary)]">{label}</dt>
                <dd className="font-medium text-[var(--lumi-text-primary)]">{value}</dd>
              </div>
            ))}
          </dl>
          {coverage.unsupported.count > 0 && (
            <div className="flex flex-col gap-1" data-coverage-unsupported="">
              <p className="text-xs text-[var(--lumi-text-secondary)]">
                不支持的语料（正文为空，永远不会被索引）共 {coverage.unsupported.count} 条：
              </p>
              <ul className="flex flex-wrap gap-1">
                {coverage.unsupported.kinds.map((entry) => (
                  <li
                    key={`${entry.kind}:${entry.reason}`}
                    data-unsupported-kind={entry.kind}
                    className="rounded-full bg-[var(--lumi-surface-selected)] px-2 py-0.5 text-[10px] text-[var(--lumi-text-secondary)]"
                  >
                    {entry.kind} · {entry.reason}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}
    </div>
  )
}

// ---- N153 分块可视预览 ----------------------------------------------------------

/** N153 查看分块：输入 ref → POST /rag/chunk-preview → 模态展示索引
 * 「将会」产生的分块（ord / 源文本坐标 / 预览文本）+ 方案元数据。 */
export function RagChunkPreviewPanel() {
  const [ref, setRef] = useState('')
  const [open, setOpen] = useState(false)
  const preview = useMutation({
    mutationFn: () => ragChunkPreview(ref.trim()),
    onSuccess: () => setOpen(true),
  })
  const result: RagChunkPreview | undefined = preview.data

  return (
    <div className="flex flex-col gap-2" data-rag-chunk-preview="">
      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault()
          if (ref.trim() !== '') preview.mutate()
        }}
      >
        <input
          type="text"
          value={ref}
          onChange={(e) => setRef(e.target.value)}
          placeholder="输入条目 ref（如 library:…）"
          aria-label="分块预览 ref"
          className="min-w-0 flex-1 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-3 py-1.5 text-sm text-[var(--lumi-text-primary)]"
        />
        <Button type="submit" variant="secondary" size="sm" disabled={preview.isPending || ref.trim() === ''}>
          {preview.isPending ? '生成中…' : '查看分块'}
        </Button>
      </form>
      {preview.isError && (
        <p role="alert" className="text-xs text-[var(--lumi-danger)]">
          {preview.error instanceof Error ? preview.error.message : '预览失败，请稍后重试。'}
        </p>
      )}
      {open && result !== undefined && (
        <Dialog open onClose={() => setOpen(false)} title="分块预览" panelClassName="max-w-2xl">
          <div className="flex flex-col gap-2" data-chunk-preview-result="">
            <p className="text-xs text-[var(--lumi-text-secondary)]">
              {result.ref}（{result.kind}）· 将产生 {result.chunks.length} 块 · 方案：单块上限{' '}
              {result.scheme.maxLen} 字符 · 重叠 {result.scheme.overlap}
            </p>
            {result.chunks.length === 0 && (
              <p className="text-xs text-[var(--lumi-text-tertiary)]">该条目没有可分块的正文。</p>
            )}
            <ul className="flex max-h-80 flex-col gap-1.5 overflow-y-auto">
              {result.chunks.map((chunk) => (
                <li
                  key={chunk.ord}
                  data-preview-chunk={chunk.ord}
                  className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-2 text-xs"
                >
                  <p className="text-[10px] text-[var(--lumi-text-tertiary)]">
                    #{chunk.ord} · 原文位置 {chunk.charStart}–{chunk.charEnd}
                  </p>
                  <p className="mt-0.5 leading-relaxed text-[var(--lumi-text-secondary)]">{chunk.text}</p>
                </li>
              ))}
            </ul>
          </div>
        </Dialog>
      )}
    </div>
  )
}

// ---- F100 -------------------------------------------------------------------

export function RagConsistencyPanel() {
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [result, setResult] = useState<{ repaired: string[]; failed: { ref: string; error: string }[] } | null>(null)
  const scan = useMutation({
    mutationFn: () => listRagInconsistencies(),
    onSuccess: () => {
      setResult(null)
      setSelected(new Set())
    },
  })
  const repair = useMutation({
    mutationFn: () => repairRagRefs([...selected]),
    onSuccess: setResult,
  })
  const items = scan.data?.items ?? []

  return (
    <div className="flex flex-col gap-2" data-rag-consistency="">
      <div className="flex items-center gap-2">
        <Button variant="secondary" size="sm" disabled={scan.isPending} onClick={() => scan.mutate()}>
          {scan.isPending ? '扫描中…' : '扫描版本一致性'}
        </Button>
        {scan.data !== undefined && (
          <span className="text-xs text-[var(--lumi-text-secondary)]">
            模型 {scan.data.modelId} · 失配 {items.length} 条
          </span>
        )}
      </div>
      {scan.isError && (
        <p role="alert" className="text-xs text-[var(--lumi-danger)]">
          扫描失败：{scan.error instanceof Error ? scan.error.message : '请稍后重试。'}
        </p>
      )}
      {scan.data !== undefined && items.length === 0 && (
        <p className="text-xs text-[var(--lumi-text-tertiary)]">没有版本失配：索引与当前内容/模型一致。</p>
      )}
      <ul className="flex flex-col gap-1">
        {items.map((item) => (
          <li
            key={item.ref}
            data-inconsistency-ref={item.ref}
            className="flex items-center gap-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2.5 py-1.5 text-xs"
          >
            <input
              type="checkbox"
              checked={selected.has(item.ref)}
              onChange={() =>
                setSelected((prev) => {
                  const next = new Set(prev)
                  if (next.has(item.ref)) next.delete(item.ref)
                  else next.add(item.ref)
                  return next
                })
              }
              aria-label={`选择修复：${item.ref}`}
            />
            <span className="min-w-0 flex-1 truncate text-[var(--lumi-text-primary)]">{item.ref}</span>
            <span
              className={cx(
                'shrink-0 rounded-full px-1.5 py-0.5 text-[10px]',
                item.basis === 'embedding_model'
                  ? 'bg-[var(--lumi-surface-selected)] text-[var(--lumi-text-secondary)]'
                  : 'bg-[var(--lumi-surface-selected)] text-[var(--lumi-text-tertiary)]',
              )}
            >
              {item.basis === 'embedding_model' ? '模型切换' : '内容变更'}
            </span>
          </li>
        ))}
      </ul>
      {items.length > 0 && (
        <div>
          <Button variant="primary" size="sm" disabled={selected.size === 0 || repair.isPending} onClick={() => repair.mutate()}>
            {repair.isPending ? '修复中…' : `修复所选（${selected.size}）`}
          </Button>
        </div>
      )}
      {result !== null && (
        <p role="status" className="text-xs text-[var(--lumi-text-primary)]" data-repair-result="">
          修复完成：成功 {result.repaired.length} 条
          {result.failed.length > 0 ? `，失败 ${result.failed.length} 条（留下次清单）` : ''}。
        </p>
      )}
      {repair.isError && (
        <p role="alert" className="text-xs text-[var(--lumi-danger)]">
          修复失败：{repair.error instanceof Error ? repair.error.message : '请稍后重试。'}
        </p>
      )}
    </div>
  )
}
