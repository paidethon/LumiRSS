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
  createRagEvalSample,
  deleteRagEvalSample,
  getRagCoverage,
  getRagSubsetJob,
  listRagEvalSamples,
  listRagExclusions,
  listRagInconsistencies,
  pauseRagRebuild,
  ragChunkPreview,
  ragTrySearch,
  rebuildRagSubset,
  rerunRagEvalSample,
  repairRagRefs,
  setRagExclusion,
  type RagChunkPreview,
  type RagCoverage,
  type RagEvalRerunDiff,
  type RagEvalSample,
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

/** N158：局部重建（重建所选）——只重嵌勾选的过期 ref（≤50）；取消 =
 * 现有暂停（重建进行中点击会翻作业行，当前页完成后停）。 */
function RebuildSelectedFlow({ coverage }: { coverage: RagCoverage }) {
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [result, setResult] = useState<{
    jobId: string
    status: string
    total: number
    updated: number
    chunks: number
    missing: string[]
  } | null>(null)
  const rebuild = useMutation({
    mutationFn: () => rebuildRagSubset([...selected]),
    onSuccess: (data) => {
      setResult(data)
      setSelected(new Set())
    },
  })
  const cancel = useMutation({
    mutationFn: () => pauseRagRebuild(),
  })
  // paused 作业轮询（进度 {done, total}）。
  const job = useQuery({
    queryKey: ['rag-subset-job', result?.jobId],
    queryFn: ({ signal }) => getRagSubsetJob(result!.jobId, signal),
    enabled: result !== null && (result.status === 'running' || result.status === 'paused'),
    refetchInterval: 1000,
  })
  const staleRefs = coverage.staleRefs ?? []
  if (staleRefs.length === 0) return null
  const refs = staleRefs.slice(0, 50)

  return (
    <div className="flex flex-col gap-1.5" data-rebuild-selected="">
      <div className="flex flex-wrap items-center gap-2">
        <Button
          variant="primary"
          size="sm"
          disabled={selected.size === 0 || rebuild.isPending}
          onClick={() => rebuild.mutate()}
        >
          {rebuild.isPending ? '重建中…' : `重建所选（${selected.size}）`}
        </Button>
        {rebuild.isPending && (
          <Button variant="ghost" size="sm" disabled={cancel.isPending} onClick={() => cancel.mutate()}>
            取消（暂停）
          </Button>
        )}
        <span className="text-[11px] text-[var(--lumi-text-tertiary)]">
          局部重建只重嵌所选条目，其余分块不动；取消 = 暂停，可续。
        </span>
      </div>
      <ul className="flex max-h-40 flex-col gap-1 overflow-y-auto">
        {refs.map((ref) => (
          <li key={ref} className="flex items-center gap-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2 py-1 text-xs">
            <input
              type="checkbox"
              checked={selected.has(ref)}
              onChange={() =>
                setSelected((prev) => {
                  const next = new Set(prev)
                  if (next.has(ref)) next.delete(ref)
                  else next.add(ref)
                  return next
                })
              }
              aria-label={`重建：${ref}`}
            />
            <span className="min-w-0 flex-1 truncate text-[var(--lumi-text-secondary)]">{ref}</span>
          </li>
        ))}
      </ul>
      {rebuild.isError && (
        <p role="alert" className="text-xs text-[var(--lumi-danger)]">
          {rebuild.error instanceof Error ? rebuild.error.message : '重建失败，请稍后重试。'}
        </p>
      )}
      {result !== null && (
        <p role="status" className="text-xs text-[var(--lumi-text-primary)]" data-rebuild-result="">
          {result.status === 'done'
            ? `局部重建完成：更新 ${result.updated}/${result.total} 条 · 新增 ${result.chunks} 块${result.missing.length > 0 ? ` · 投影缺失 ${result.missing.length} 条（诚实跳过）` : ''}。`
            : result.status === 'paused'
              ? `已暂停（job ${result.jobId.slice(0, 8)}…）——进度可在上方状态里查看，再次重建其余条目可续。`
              : `状态：${result.status}`}
        </p>
      )}
      {job.data !== undefined && job.data.pending.length > 0 && (
        <p className="text-[11px] text-[var(--lumi-text-tertiary)]">
          进度 {job.data.done}/{job.data.total} · 待续 {job.data.pending.length} 条
        </p>
      )}
    </div>
  )
}

/** N152 覆盖率卡片：语料 ↔ 索引真实分桶（indexable/indexed/stale/failed
 * 来自行与作业，unsupported 按 kind 给原因）。纯只读盘点。
 * N158：过期 ref 明细（staleRefs）→「重建所选」勾选流。 */
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
          <RebuildSelectedFlow coverage={coverage} />
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

// ---- N159 检索质量收藏（评测样例） ---------------------------------------------

/** N159 评测样例面板：保存「查询 + 期望命中」（保存时服务端立即检索并
 * 捕获实际命中），rerun 重放同一查询并差分（hitExpected / missed /
 * newHits）。样例私有（每用户库），绝不进入任何导出/分享包/备份组件。
 * 上限 50 条（满了服务端 409 诚实拒绝，绝不静默挤出最旧行）。 */
export function RagEvalSamplesPanel() {
  const samples = useQuery({
    queryKey: ['rag-eval-samples'],
    queryFn: ({ signal }) => listRagEvalSamples(signal),
  })
  const queryClient = useQueryClient()
  const [query, setQuery] = useState('')
  const [expected, setExpected] = useState('')
  const [diffs, setDiffs] = useState<Record<string, RagEvalRerunDiff>>({})
  const invalidate = async () => {
    await queryClient.invalidateQueries({ queryKey: ['rag-eval-samples'] })
  }
  const save = useMutation({
    mutationFn: () =>
      createRagEvalSample(
        query.trim(),
        expected
          .split(/[,，;；\s]+/)
          .map((s) => s.trim())
          .filter((s) => s !== ''),
      ),
    onSuccess: async () => {
      setQuery('')
      setExpected('')
      await invalidate()
    },
  })
  const remove = useMutation({
    mutationFn: async (id: string) => {
      await deleteRagEvalSample(id)
      return id
    },
    onSuccess: async (deletedId: string) => {
      setDiffs((prev) => {
        const next = { ...prev }
        delete next[deletedId]
        return next
      })
      await invalidate()
    },
  })
  const rerun = useMutation({
    mutationFn: (id: string) => rerunRagEvalSample(id),
    onSuccess: (diff) => {
      setDiffs((prev) => ({ ...prev, [diff.sampleId]: diff }))
    },
  })
  const items: RagEvalSample[] = samples.data?.items ?? []

  return (
    <div className="flex flex-col gap-2" data-rag-eval-samples="">
      <p className="text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
        保存时服务端会立即执行一次真实检索并捕获当时的实际命中；之后可
        「重放」同一查询与存档差分，观察索引漂移。样例仅存于本账户。
      </p>
      <form
        className="flex flex-col gap-1.5"
        onSubmit={(e) => {
          e.preventDefault()
          if (query.trim() !== '') save.mutate()
        }}
        data-eval-sample-create=""
      >
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="评测查询…"
          aria-label="评测查询"
          className="rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-3 py-1.5 text-sm text-[var(--lumi-text-primary)]"
        />
        <input
          type="text"
          value={expected}
          onChange={(e) => setExpected(e.target.value)}
          placeholder="期望命中的 ref（逗号/空格分隔，可空）"
          aria-label="期望命中 ref"
          className="rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-3 py-1.5 text-sm text-[var(--lumi-text-primary)]"
        />
        <div>
          <Button type="submit" variant="secondary" size="sm" disabled={query.trim() === '' || save.isPending}>
            {save.isPending ? '保存中…' : '保存评测样例'}
          </Button>
        </div>
      </form>
      {save.isError && (
        <p role="alert" className="text-xs text-[var(--lumi-danger)]">
          {save.error instanceof Error ? save.error.message : '保存失败，请稍后重试。'}
        </p>
      )}
      {samples.isPending && <Skeleton className="h-16 w-full" />}
      {samples.isError && (
        <p role="alert" className="text-xs text-[var(--lumi-danger)]">
          样例加载失败：{samples.error instanceof Error ? samples.error.message : '请稍后重试。'}
        </p>
      )}
      {!samples.isPending && items.length === 0 && !samples.isError && (
        <p className="text-xs text-[var(--lumi-text-tertiary)]">
          还没有评测样例（上限 {samples.data?.cap ?? 50} 条）。
        </p>
      )}
      <ul className="flex flex-col gap-1.5">
        {items.map((sample) => {
          const diff = diffs[sample.id]
          return (
            <li
              key={sample.id}
              data-eval-sample={sample.id}
              className="flex flex-col gap-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2.5 py-1.5 text-xs"
            >
              <div className="flex items-center gap-2">
                <span className="min-w-0 flex-1 truncate font-medium text-[var(--lumi-text-primary)]">
                  {sample.query}
                </span>
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={rerun.isPending}
                  onClick={() => rerun.mutate(sample.id)}
                >
                  {rerun.isPending ? '重放中…' : '重放'}
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={remove.isPending}
                  aria-label={`删除样例 ${sample.query}`}
                  onClick={() => remove.mutate(sample.id)}
                >
                  删除
                </Button>
              </div>
              <p className="text-[11px] text-[var(--lumi-text-tertiary)]">
                期望 {sample.expectedRefs.length} 条 · 保存时实际命中 {sample.actualRefs.length} 条
              </p>
              {diff !== undefined && (
                <div className="flex flex-col gap-0.5 rounded-[var(--lumi-radius-md)] bg-[var(--lumi-surface-selected)] p-1.5" data-rerun-diff="">
                  <span className="text-[var(--lumi-text-primary)]">
                    期望仍命中 {diff.hitExpected.length} · 期望丢失 {diff.missed.length} · 新命中{' '}
                    {diff.newHits.length}
                  </span>
                  {diff.missed.length > 0 && (
                    <span className="text-[var(--lumi-text-secondary)]">
                      丢失：{diff.missed.join('、')}
                    </span>
                  )}
                  {diff.newHits.length > 0 && (
                    <span className="text-[var(--lumi-text-secondary)]">
                      新命中：{diff.newHits.join('、')}
                    </span>
                  )}
                </div>
              )}
              {rerun.isError && rerun.variables === sample.id && (
                <p role="alert" className="text-xs text-[var(--lumi-danger)]">
                  {rerun.error instanceof Error ? rerun.error.message : '重放失败。'}
                </p>
              )}
            </li>
          )
        })}
      </ul>
    </div>
  )
}
