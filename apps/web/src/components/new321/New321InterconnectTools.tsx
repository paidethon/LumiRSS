/** NEW-321..330 Obsidian 与本地资料互通 — 组合面板（两级情境展开）。
 *
 * - NEW-321 标签映射：源标签 → 个人标签规则，预览层级/合并/冲突，
 *   物化只改变导入层；
 * - NEW-322 链接解析报告：明确/歧义/失效 + 逐项纠正导入映射；
 * - NEW-323 同步审批：预览差异清单（零写入）→ 确认后更新镜像；
 * - NEW-324 批注 Markdown 输出：生成文件内容，用户自行保存入库；
 * - NEW-325 多根目录档案：独立只读档案 + 忽略规则 + 各自扫描状态；
 * - NEW-326 可移植打包：选中笔记 + 允许附件 → 相对链接 zip（越界校验）；
 * - NEW-327 属性列映射：frontmatter 字段 → 可见列 + 按属性筛选；
 * - NEW-328 冲突收件箱：个人修正 vs 源更新并排，显式二选一；
 * - NEW-329 断开连接：撤销授权停止扫描，副本去留用户显式二选一；
 * - NEW-330 重定位向导：按校验和匹配原条目，不重复导入。
 *
 * 服务真源在 BFF（routers/new32*.py / new330*.py）；本组件只做真实
 * 调用 + 诚实状态（loading/error/empty），不做客户端转译。Vault 只读
 * 不变：全部操作作用于 Lumi 侧导入层与档案。 */

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  applyRelocation,
  applySync,
  buildLinkReport,
  bundleDownloadUrl,
  createBundle,
  createRootProfile,
  decideRootCopies,
  detectConflicts,
  disconnectRoot,
  exportAnnotationsMarkdown,
  filterNotesByProperty,
  listAnnotationExports,
  listLinkCorrections,
  listOpenConflicts,
  listPropertyColumns,
  listRootNotes,
  listRootProfiles,
  listSyncApprovals,
  listTagRules,
  materializeTagMapping,
  previewRelocation,
  previewSync,
  previewTagMapping,
  putLinkCorrection,
  putPersonalCorrection,
  putPropertyColumn,
  putTagRule,
  reconnectRoot,
  resolveConflict,
  scanRootProfile,
  type LinkReportItem,
  type RelocationPlan,
  type RootProfile,
  type SyncPlan,
  type TagPreview,
} from '../../api/new321'
import { Button } from '../ui/Button'
import {
  NoteText,
  StatusLine,
  SubSection,
  errorText,
  inputClass,
} from './parts'

export function New321InterconnectTools() {
  const [open, setOpen] = useState(false)
  return (
    <section data-new321-tools="">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="min-h-8 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2.5 text-sm font-medium text-[var(--lumi-text-primary)] hover:bg-[var(--lumi-surface-hover)]"
      >
        Obsidian 互通工具（{open ? '收起' : '展开'}）
      </button>
      {open && (
        <div className="mt-2 flex flex-col gap-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] p-3">
          <TagMappingSection />
          <LinkReportSection />
          <SyncApprovalSection />
          <AnnotationExportSection />
          <RootProfilesSection />
          <BundleSection />
          <PropertyColumnsSection />
          <ConflictInboxSection />
          <RelocationSection />
        </div>
      )}
    </section>
  )
}

// ---- NEW-321 标签映射 --------------------------------------------------------

function TagMappingSection() {
  return (
    <SubSection id="tag-mapping" label="标签映射规则（源库标签 → 个人标签，只改导入层）">
      {(open) => <TagMappingBody open={open} />}
    </SubSection>
  )
}

function TagMappingBody({ open }: { open: boolean }) {
  const [sourceTag, setSourceTag] = useState('')
  const [targetTag, setTargetTag] = useState('')
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  // enabled=open：折叠零查询（MASTER §6）。
  const preview = useQuery({
    queryKey: ['new321-tag-preview'],
    queryFn: previewTagMapping,
    enabled: open,
  })
  const rules = useQuery({
    queryKey: ['new321-tag-rules'],
    queryFn: listTagRules,
    enabled: open,
  })

  async function run(action: () => Promise<unknown>, message: string) {
    setBusy(true)
    setError(null)
    setStatus(null)
    try {
      await action()
      setStatus(message)
      await Promise.all([preview.refetch(), rules.refetch()])
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-end gap-2">
        <label className="flex flex-col gap-1">
          <span className="text-xs text-[var(--lumi-text-secondary)]">源标签</span>
          <input type="text" value={sourceTag} aria-label="源标签"
            onChange={(e) => setSourceTag(e.target.value)} className={inputClass} />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-[var(--lumi-text-secondary)]">个人标签（可用 / 分层级）</span>
          <input type="text" value={targetTag} aria-label="个人标签"
            onChange={(e) => setTargetTag(e.target.value)} className={inputClass} />
        </label>
        <Button variant="primary" size="sm" disabled={busy || !sourceTag.trim() || !targetTag.trim()}
          onClick={() => void run(() => putTagRule(sourceTag.trim(), targetTag.trim()), '规则已保存。')}>
          保存规则
        </Button>
        <Button variant="secondary" size="sm" disabled={busy}
          onClick={() => void run(() => materializeTagMapping(), '导入层已按当前规则重建。')}>
          重建导入层
        </Button>
      </div>
      {status && <StatusLine tone="ok">{status}</StatusLine>}
      {error && <StatusLine tone="error">{error}</StatusLine>}
      {preview.isPending ? (
        <NoteText>加载中…</NoteText>
      ) : preview.isError ? (
        <StatusLine tone="error">{errorText(preview.error)}</StatusLine>
      ) : (
        <TagPreviewList preview={preview.data} />
      )}
    </div>
  )
}

function TagPreviewList({ preview }: { preview: TagPreview }) {
  if (preview.sourceTags.length === 0) {
    return <NoteText>投影中还没有任何标签（先扫描 Vault）。</NoteText>
  }
  return (
    <div className="flex flex-col gap-1" data-new321-tag-preview="">
      <NoteText>
        源标签 {preview.sourceTags.length} 个；规则 {preview.mappings.filter((m) => m.mapped).length} 条。
        预览零写入，物化只改变导入层。
      </NoteText>
      <ul className="ml-4 list-disc text-xs text-[var(--lumi-text-secondary)]">
        {preview.mappings.slice(0, 8).map((m) => (
          <li key={m.sourceTag}>
            #{m.sourceTag} → #{m.targetTag}
            {preview.hierarchy[m.sourceTag]?.length ? `（层级：${preview.hierarchy[m.sourceTag].join(' / ')}）` : ''}
            {m.mapped ? '' : '（未映射，原样）'}
          </li>
        ))}
      </ul>
      {preview.conflicts.length > 0 && (
        <StatusLine tone="error">
          冲突 {preview.conflicts.length} 条：{preview.conflicts[0].detail}
        </StatusLine>
      )}
      {preview.merges.length > 0 && (
        <NoteText>
          合并 {preview.merges.length} 处（多个源标签汇入同一个人标签）。
        </NoteText>
      )}
    </div>
  )
}

// ---- NEW-322 链接解析报告 ------------------------------------------------------

function LinkReportSection() {
  return (
    <SubSection id="link-report" label="链接解析报告（明确 / 歧义 / 失效）">
      {() => <LinkReportBody />}
    </SubSection>
  )
}

function LinkReportBody() {
  const [items, setItems] = useState<LinkReportItem[] | null>(null)
  const [counts, setCounts] = useState<Record<string, number> | null>(null)
  const [noteUuid, setNoteUuid] = useState('')
  const [raw, setRaw] = useState('')
  const [targetUuid, setTargetUuid] = useState('')
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const corrections = useQuery({
    queryKey: ['new321-link-corrections'],
    queryFn: listLinkCorrections,
  })

  async function runReport() {
    setBusy(true)
    setError(null)
    setStatus(null)
    try {
      const report = await buildLinkReport()
      setItems(report.items)
      setCounts(report.counts)
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  async function saveCorrection() {
    setBusy(true)
    setError(null)
    setStatus(null)
    try {
      await putLinkCorrection({
        noteUuid: noteUuid.trim().replace(/^library:/, ''),
        raw: raw.trim(),
        targetUuid: targetUuid.trim().replace(/^library:/, ''),
      })
      setStatus('纠正已记录：该链接的导入映射将按指定目标解析。')
      await corrections.refetch()
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <Button variant="secondary" size="sm" disabled={busy} onClick={() => void runReport()}>
        生成报告（全部笔记）
      </Button>
      {error && <StatusLine tone="error">{error}</StatusLine>}
      {status && <StatusLine tone="ok">{status}</StatusLine>}
      {counts !== null && items !== null && (
        <div data-new321-link-report="">
          <NoteText>
            明确 {counts.resolved ?? 0} · 歧义 {counts.ambiguous ?? 0} · 失效 {counts.broken ?? 0} ·
            已纠正 {counts.corrected ?? 0}
          </NoteText>
          <ul className="ml-4 list-disc text-xs text-[var(--lumi-text-secondary)]">
            {items.slice(0, 5).map((item) => (
              <li key={`${item.noteUuid}-${item.raw}`}>
                [[{item.raw}]]：{item.status}
                {item.candidates.length > 0 ? `（候选：${item.candidates.join('、')}）` : ''}
              </li>
            ))}
          </ul>
        </div>
      )}
      <div className="flex flex-wrap items-end gap-2">
        <label className="flex flex-1 flex-col gap-1">
          <span className="text-xs text-[var(--lumi-text-secondary)]">笔记 uuid</span>
          <input type="text" value={noteUuid} aria-label="纠正的笔记 uuid"
            onChange={(e) => setNoteUuid(e.target.value)} className={inputClass} />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-[var(--lumi-text-secondary)]">链接原文</span>
          <input type="text" value={raw} aria-label="纠正的链接原文"
            onChange={(e) => setRaw(e.target.value)} className={inputClass} />
        </label>
        <label className="flex flex-1 flex-col gap-1">
          <span className="text-xs text-[var(--lumi-text-secondary)]">目标笔记 uuid</span>
          <input type="text" value={targetUuid} aria-label="纠正目标笔记 uuid"
            onChange={(e) => setTargetUuid(e.target.value)} className={inputClass} />
        </label>
        <Button variant="primary" size="sm"
          disabled={busy || !noteUuid.trim() || !raw.trim() || !targetUuid.trim()}
          onClick={() => void saveCorrection()}>
          记录纠正
        </Button>
      </div>
      {corrections.isPending ? (
        <NoteText>加载中…</NoteText>
      ) : corrections.isError ? (
        <StatusLine tone="error">{errorText(corrections.error)}</StatusLine>
      ) : corrections.data.corrections.length === 0 ? (
        <NoteText>还没有纠正记录。</NoteText>
      ) : (
        <ul className="ml-4 list-disc text-xs text-[var(--lumi-text-secondary)]" data-new321-link-corrections="">
          {corrections.data.corrections.slice(0, 5).map((c) => (
            <li key={`${c.noteUuid}-${c.raw}`}>
              [[{c.raw}]] → {c.targetUuid}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

// ---- NEW-323 同步审批 ----------------------------------------------------------

function SyncApprovalSection() {
  return (
    <SubSection id="sync-approval" label="增量同步审批（预览清单 → 确认后更新镜像）">
      {(open) => <SyncApprovalBody open={open} />}
    </SubSection>
  )
}

function SyncApprovalBody({ open }: { open: boolean }) {
  const [plan, setPlan] = useState<SyncPlan | null>(null)
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const approvals = useQuery({
    queryKey: ['new321-sync-approvals'],
    queryFn: listSyncApprovals,
    enabled: open,
  })

  async function runPreview() {
    setBusy(true)
    setError(null)
    setStatus(null)
    try {
      setPlan(await previewSync())
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  async function runApply() {
    if (plan === null) return
    setBusy(true)
    setError(null)
    try {
      const done = await applySync(plan.id)
      setStatus(`镜像已更新：新增 ${done.report.added} · 修改 ${done.report.changed} · 删除 ${done.report.removed}。`)
      setPlan(null)
      await approvals.refetch()
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="secondary" size="sm" disabled={busy} onClick={() => void runPreview()}>
          预览同步差异
        </Button>
        {plan !== null && (
          <Button variant="primary" size="sm" disabled={busy} onClick={() => void runApply()}>
            确认同步（更新镜像）
          </Button>
        )}
      </div>
      {error && <StatusLine tone="error">{error}</StatusLine>}
      {status && <StatusLine tone="ok">{status}</StatusLine>}
      {plan !== null && (
        <div data-new321-sync-plan="">
          <NoteText>
            新增 {plan.added} · 修改 {plan.changed} · 删除 {plan.removed} · 改名 {plan.renames}；
            预览零写入，确认后才更新镜像（绝不写源库）。
          </NoteText>
          <ul className="ml-4 list-disc text-xs text-[var(--lumi-text-secondary)]">
            {(plan.files?.added?.items ?? []).slice(0, 3).map((path) => (
              <li key={path}>新增：{path}</li>
            ))}
            {(plan.files?.changed?.items ?? []).slice(0, 3).map((path) => (
              <li key={path}>修改：{path}</li>
            ))}
            {(plan.files?.removed?.items ?? []).slice(0, 3).map((path) => (
              <li key={path}>删除：{path}</li>
            ))}
          </ul>
        </div>
      )}
      {approvals.isPending ? (
        <NoteText>加载中…</NoteText>
      ) : approvals.isError ? (
        <StatusLine tone="error">{errorText(approvals.error)}</StatusLine>
      ) : approvals.data.approvals.length === 0 ? (
        <NoteText>还没有同步审批记录。</NoteText>
      ) : (
        <ul className="ml-4 list-disc text-xs text-[var(--lumi-text-secondary)]" data-new321-sync-approvals="">
          {approvals.data.approvals.slice(0, 3).map((a) => (
            <li key={a.id}>
              {a.status === 'applied' ? '已应用' : a.status === 'pending' ? '待确认' : '已过期'}
              （{a.createdAt}）
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

// ---- NEW-324 批注 Markdown 输出 --------------------------------------------------

function AnnotationExportSection() {
  return (
    <SubSection id="annotation-export" label="阅读批注 Markdown 输出（生成文件，自行保存）">
      {() => <AnnotationExportBody />}
    </SubSection>
  )
}

function AnnotationExportBody() {
  const [refsText, setRefsText] = useState('')
  const [result, setResult] = useState<{ filename: string; content: string; annotationCount: number } | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const history = useQuery({
    queryKey: ['new321-annotation-exports'],
    queryFn: listAnnotationExports,
  })

  async function runExport() {
    setBusy(true)
    setError(null)
    setResult(null)
    try {
      const refs = refsText
        .split('\n')
        .map((line) => line.trim())
        .filter((line) => line !== '')
      const done = await exportAnnotationsMarkdown(refs)
      setResult({ filename: done.filename, content: done.content, annotationCount: done.annotationCount })
      await history.refetch()
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <label className="flex flex-col gap-1">
        <span className="text-xs text-[var(--lumi-text-secondary)]">文章 ref（每行一个，如 rss:…）</span>
        <textarea value={refsText} aria-label="导出批注的文章 ref"
          onChange={(e) => setRefsText(e.target.value)} rows={3} className={inputClass} />
      </label>
      <Button variant="primary" size="sm" disabled={busy || refsText.trim() === ''}
        onClick={() => void runExport()}>
        生成 Markdown（{refsText.split('\n').filter((l) => l.trim() !== '').length} 篇）
      </Button>
      {error && <StatusLine tone="error">{error}</StatusLine>}
      {result !== null && (
        <div className="flex flex-col gap-1" data-new321-annotation-export="">
          <StatusLine tone="ok">
            已生成 {result.filename}（{result.annotationCount} 条批注）。Lumi 不代写文件：
            请复制下方内容自行保存进你的资料库；源库保持只读。
          </StatusLine>
          <textarea readOnly value={result.content} aria-label="批注 Markdown 内容" rows={10} className={inputClass} />
        </div>
      )}
      {history.isPending ? (
        <NoteText>加载中…</NoteText>
      ) : history.isError ? (
        <StatusLine tone="error">{errorText(history.error)}</StatusLine>
      ) : history.data.exports.length === 0 ? (
        <NoteText>还没有导出记录。</NoteText>
      ) : (
        <ul className="ml-4 list-disc text-xs text-[var(--lumi-text-secondary)]" data-new321-annotation-history="">
          {history.data.exports.slice(0, 3).map((e) => (
            <li key={e.id}>{e.filename}（{e.annotationCount} 条批注）</li>
          ))}
        </ul>
      )}
    </div>
  )
}

// ---- NEW-325 / NEW-329 多根目录档案 + 断开连接 -------------------------------------

function RootProfilesSection() {
  return (
    <SubSection id="root-profiles" label="多根目录档案（独立只读档案 + 忽略规则 + 断开连接）">
      {(open) => <RootProfilesBody open={open} />}
    </SubSection>
  )
}

function RootProfilesBody({ open }: { open: boolean }) {
  const [label, setLabel] = useState('')
  const [rootPath, setRootPath] = useState('')
  const [ignoreGlobs, setIgnoreGlobs] = useState('')
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [scanReport, setScanReport] = useState<string | null>(null)
  const [notesFor, setNotesFor] = useState<string | null>(null)
  const [notePaths, setNotePaths] = useState<string[]>([])
  const roots = useQuery({
    queryKey: ['new321-root-profiles'],
    queryFn: listRootProfiles,
    enabled: open,
  })

  async function run(action: () => Promise<unknown>, message: string) {
    setBusy(true)
    setError(null)
    setStatus(null)
    try {
      await action()
      setStatus(message)
      await roots.refetch()
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  async function scan(root: RootProfile) {
    setBusy(true)
    setError(null)
    try {
      const report = await scanRootProfile(root.id)
      setScanReport(`「${root.label}」扫描完成：新增 ${report.added} · 修改 ${report.changed} · 删除 ${report.removed}。`)
      await roots.refetch()
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  async function showNotes(root: RootProfile) {
    if (notesFor === root.id) {
      setNotesFor(null)
      return
    }
    setBusy(true)
    setError(null)
    try {
      const listing = await listRootNotes(root.id)
      setNotePaths(listing.notes.map((n) => n.relPath))
      setNotesFor(root.id)
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-end gap-2">
        <label className="flex flex-col gap-1">
          <span className="text-xs text-[var(--lumi-text-secondary)]">档案名称</span>
          <input type="text" value={label} aria-label="资料根档案名称"
            onChange={(e) => setLabel(e.target.value)} className={inputClass} />
        </label>
        <label className="flex flex-1 flex-col gap-1">
          <span className="text-xs text-[var(--lumi-text-secondary)]">根目录绝对路径</span>
          <input type="text" value={rootPath} aria-label="资料根目录路径"
            onChange={(e) => setRootPath(e.target.value)} className={inputClass} />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-[var(--lumi-text-secondary)]">忽略规则（逗号分隔 glob）</span>
          <input type="text" value={ignoreGlobs} aria-label="忽略规则"
            onChange={(e) => setIgnoreGlobs(e.target.value)} className={inputClass} />
        </label>
        <Button variant="primary" size="sm" disabled={busy || !label.trim() || !rootPath.trim()}
          onClick={() =>
            void run(
              () =>
                createRootProfile({
                  label: label.trim(),
                  rootPath: rootPath.trim(),
                  ignoreGlobs: ignoreGlobs.split(',').map((g) => g.trim()).filter((g) => g !== ''),
                }),
              '档案已建立（只读，不改动该目录）。',
            )
          }
        >
          建立档案
        </Button>
      </div>
      {error && <StatusLine tone="error">{error}</StatusLine>}
      {status && <StatusLine tone="ok">{status}</StatusLine>}
      {scanReport && <StatusLine tone="info">{scanReport}</StatusLine>}
      {roots.isPending ? (
        <NoteText>加载中…</NoteText>
      ) : roots.isError ? (
        <StatusLine tone="error">{errorText(roots.error)}</StatusLine>
      ) : roots.data.roots.length === 0 ? (
        <NoteText>还没有资料根档案。</NoteText>
      ) : (
        <ul className="flex flex-col gap-2" data-new321-roots="">
          {roots.data.roots.map((root) => (
            <li key={root.id} className="flex flex-col gap-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-2">
              <span className="flex flex-wrap items-center gap-x-2 text-sm text-[var(--lumi-text-primary)]">
                {root.label}
                <span className="text-xs text-[var(--lumi-text-tertiary)]">
                  {root.noteCount} 条 · {root.authorized ? '已授权' : '已断开'}
                  {root.copiesPolicy ? `（副本已${root.copiesPolicy === 'kept' ? '保留' : '删除'}）` : ''}
                  {root.lastScanAt ? '' : ' · 从未扫描'}
                </span>
              </span>
              <span className="text-xs text-[var(--lumi-text-tertiary)]">{root.rootPath}</span>
              {root.lastError && <StatusLine tone="error">{root.lastError}</StatusLine>}
              <span className="flex flex-wrap gap-1.5">
                <Button variant="secondary" size="sm" disabled={busy || !root.authorized}
                  onClick={() => void scan(root)}>
                  扫描
                </Button>
                <Button variant="ghost" size="sm" disabled={busy} onClick={() => void showNotes(root)}>
                  {notesFor === root.id ? '收起笔记' : '查看笔记'}
                </Button>
                {root.authorized ? (
                  <Button variant="ghost" size="sm" disabled={busy}
                    onClick={() => void run(() => disconnectRoot(root.id), `「${root.label}」已断开：扫描停止。`)}>
                    断开连接
                  </Button>
                ) : (
                  <>
                    <Button variant="ghost" size="sm" disabled={busy}
                      onClick={() => void run(() => decideRootCopies(root.id, 'keep'), '导入副本已保留。')}>
                      保留副本
                    </Button>
                    <Button variant="ghost" size="sm" disabled={busy}
                      onClick={() => void run(() => decideRootCopies(root.id, 'delete'), '本应用副本已删除（源目录未动）。')}>
                      删除副本
                    </Button>
                    <Button variant="secondary" size="sm" disabled={busy}
                      onClick={() => void run(() => reconnectRoot(root.id), `「${root.label}」已重新授权。`)}>
                      重新授权
                    </Button>
                  </>
                )}
              </span>
              {notesFor === root.id && (
                <ul className="ml-4 list-disc text-xs text-[var(--lumi-text-secondary)]" data-new321-root-notes="">
                  {notePaths.length === 0 ? <li>该档案还没有笔记。</li> : notePaths.slice(0, 5).map((path) => (
                    <li key={path}>{path}</li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

// ---- NEW-326 可移植打包 --------------------------------------------------------

function BundleSection() {
  return (
    <SubSection id="bundle" label="可移植打包（选中笔记 + 允许的附件 → 相对链接 zip）">
      {() => <BundleBody />}
    </SubSection>
  )
}

function BundleBody() {
  const [refsText, setRefsText] = useState('')
  const [manifest, setManifest] = useState<{ id: string; noteCount: number; attachmentCount: number; violationCount: number } | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function runBundle() {
    setBusy(true)
    setError(null)
    setManifest(null)
    try {
      const refs = refsText.split('\n').map((l) => l.trim().replace(/^library:/, '')).filter((l) => l !== '')
      setManifest(await createBundle(refs))
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <label className="flex flex-col gap-1">
        <span className="text-xs text-[var(--lumi-text-secondary)]">笔记 uuid（每行一个）</span>
        <textarea value={refsText} aria-label="打包的笔记 uuid"
          onChange={(e) => setRefsText(e.target.value)} rows={3} className={inputClass} />
      </label>
      <Button variant="primary" size="sm" disabled={busy || refsText.trim() === ''}
        onClick={() => void runBundle()}>
        组包（只读 Vault）
      </Button>
      {error && <StatusLine tone="error">{error}</StatusLine>}
      {manifest !== null && (
        <div className="flex flex-col gap-1" data-new321-bundle="">
          <StatusLine tone="ok">
            包已就绪：{manifest.noteCount} 篇笔记 · {manifest.attachmentCount} 个附件 ·
            越界/缺失 {manifest.violationCount} 条（已排除并记录）。
          </StatusLine>
          <a
            href={bundleDownloadUrl(manifest.id)}
            className="inline-flex items-center gap-1 text-sm text-[var(--lumi-accent-text)] hover:underline"
          >
            下载 zip（notes/ + attachments/ + manifest.json）
          </a>
        </div>
      )}
    </div>
  )
}

// ---- NEW-327 属性列映射 --------------------------------------------------------

function PropertyColumnsSection() {
  return (
    <SubSection id="property-columns" label="笔记属性列映射（frontmatter → 可见列 + 筛选）">
      {(open) => <PropertyColumnsBody open={open} />}
    </SubSection>
  )
}

function PropertyColumnsBody({ open }: { open: boolean }) {
  const [field, setField] = useState('')
  const [label, setLabel] = useState('')
  const [filterField, setFilterField] = useState('')
  const [filterValue, setFilterValue] = useState('')
  const [hits, setHits] = useState<{ relPath: string; title: string }[] | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const columns = useQuery({
    queryKey: ['new321-property-columns'],
    queryFn: listPropertyColumns,
    enabled: open,
  })

  async function saveColumn() {
    setBusy(true)
    setError(null)
    try {
      await putPropertyColumn({ field: field.trim(), label: label.trim(), visible: true, filterable: true })
      await columns.refetch()
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  async function runFilter() {
    setBusy(true)
    setError(null)
    try {
      const result = await filterNotesByProperty(filterField.trim(), filterValue.trim())
      setHits(result.notes)
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex flex-col gap-3">
      {columns.isPending ? (
        <NoteText>加载中…</NoteText>
      ) : columns.isError ? (
        <StatusLine tone="error">{errorText(columns.error)}</StatusLine>
      ) : (
        <NoteText>
          投影中出现过 {columns.data.fields.length} 个 frontmatter 字段
          （{columns.data.fields.slice(0, 5).map((f) => f.field).join('、')}
          {columns.data.fields.length > 5 ? ' …' : ''}）；已配置 {columns.data.columns.length} 列。原文件格式不变。
        </NoteText>
      )}
      <div className="flex flex-wrap items-end gap-2">
        <label className="flex flex-col gap-1">
          <span className="text-xs text-[var(--lumi-text-secondary)]">字段名</span>
          <input type="text" value={field} aria-label="属性字段名"
            onChange={(e) => setField(e.target.value)} className={inputClass} />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-[var(--lumi-text-secondary)]">列名（展示用）</span>
          <input type="text" value={label} aria-label="属性列名"
            onChange={(e) => setLabel(e.target.value)} className={inputClass} />
        </label>
        <Button variant="primary" size="sm" disabled={busy || !field.trim()}
          onClick={() => void saveColumn()}>
          保存列映射
        </Button>
      </div>
      <div className="flex flex-wrap items-end gap-2">
        <label className="flex flex-col gap-1">
          <span className="text-xs text-[var(--lumi-text-secondary)]">筛选字段</span>
          <input type="text" value={filterField} aria-label="筛选字段"
            onChange={(e) => setFilterField(e.target.value)} className={inputClass} />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-[var(--lumi-text-secondary)]">筛选值</span>
          <input type="text" value={filterValue} aria-label="筛选值"
            onChange={(e) => setFilterValue(e.target.value)} className={inputClass} />
        </label>
        <Button variant="secondary" size="sm" disabled={busy || !filterField.trim()}
          onClick={() => void runFilter()}>
          按属性筛选
        </Button>
      </div>
      {error && <StatusLine tone="error">{error}</StatusLine>}
      {hits !== null && (
        <ul className="ml-4 list-disc text-xs text-[var(--lumi-text-secondary)]" data-new321-property-hits="">
          {hits.length === 0 ? <li>没有匹配的笔记。</li> : hits.slice(0, 5).map((n) => (
            <li key={n.relPath}>{n.title}（{n.relPath}）</li>
          ))}
        </ul>
      )}
    </div>
  )
}

// ---- NEW-328 冲突收件箱 --------------------------------------------------------

function ConflictInboxSection() {
  return (
    <SubSection id="conflict-inbox" label="库同步冲突收件箱（个人修正 vs 源更新）">
      {(open) => <ConflictInboxBody open={open} />}
    </SubSection>
  )
}

function ConflictInboxBody({ open }: { open: boolean }) {
  const [noteUuid, setNoteUuid] = useState('')
  const [personalTitle, setPersonalTitle] = useState('')
  const [detectSummary, setDetectSummary] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const conflicts = useQuery({
    queryKey: ['new321-conflicts'],
    queryFn: listOpenConflicts,
    enabled: open,
  })

  async function run(action: () => Promise<unknown>, message: (result: unknown) => string) {
    setBusy(true)
    setError(null)
    try {
      const result = await action()
      setDetectSummary(message(result))
      await conflicts.refetch()
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-end gap-2">
        <label className="flex flex-1 flex-col gap-1">
          <span className="text-xs text-[var(--lumi-text-secondary)]">笔记 uuid</span>
          <input type="text" value={noteUuid} aria-label="个人修正的笔记 uuid"
            onChange={(e) => setNoteUuid(e.target.value)} className={inputClass} />
        </label>
        <label className="flex flex-1 flex-col gap-1">
          <span className="text-xs text-[var(--lumi-text-secondary)]">个人标题修正</span>
          <input type="text" value={personalTitle} aria-label="个人标题修正"
            onChange={(e) => setPersonalTitle(e.target.value)} className={inputClass} />
        </label>
        <Button variant="primary" size="sm" disabled={busy || !noteUuid.trim()}
          onClick={() =>
            void run(
              () => putPersonalCorrection({ noteUuid: noteUuid.trim().replace(/^library:/, ''), personalTitle: personalTitle.trim() }),
              () => '个人修正已记录（Lumi 侧独立层，源文件未动）。',
            )
          }
        >
          记录修正
        </Button>
        <Button variant="secondary" size="sm" disabled={busy}
          onClick={() =>
            void run(
              () => detectConflicts(),
              (result) => {
                const d = result as { checked: number; opened: number }
                return `检测完成：${d.checked} 条修正，新冲突 ${d.opened} 条。`
              },
            )
          }
        >
          检测源更新冲突
        </Button>
      </div>
      {error && <StatusLine tone="error">{error}</StatusLine>}
      {detectSummary && <StatusLine tone="info">{detectSummary}</StatusLine>}
      {conflicts.isPending ? (
        <NoteText>加载中…</NoteText>
      ) : conflicts.isError ? (
        <StatusLine tone="error">{errorText(conflicts.error)}</StatusLine>
      ) : conflicts.data.conflicts.length === 0 ? (
        <NoteText>收件箱为空：没有待决策的冲突。</NoteText>
      ) : (
        <ul className="flex flex-col gap-2" data-new321-conflicts="">
          {conflicts.data.conflicts.map((conflict: SyncConflict) => (
            <li key={conflict.id} className="flex flex-col gap-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-2">
              <div className="grid grid-cols-2 gap-2 text-xs">
                <div>
                  <span className="font-medium text-[var(--lumi-text-primary)]">源版本</span>
                  <p className="text-[var(--lumi-text-secondary)]">{conflict.source.title}</p>
                  <p className="text-[var(--lumi-text-tertiary)]">{conflict.source.excerpt.slice(0, 60)}</p>
                </div>
                <div>
                  <span className="font-medium text-[var(--lumi-text-primary)]">个人修正</span>
                  <p className="text-[var(--lumi-text-secondary)]">{conflict.personal.title || '（无）'}</p>
                  <p className="text-[var(--lumi-text-tertiary)]">{conflict.personal.note.slice(0, 60)}</p>
                </div>
              </div>
              <span className="flex gap-1.5">
                <Button variant="secondary" size="sm" disabled={busy}
                  onClick={() =>
                    void run(
                      () => resolveConflict(conflict.id, 'keep_independent'),
                      () => '已保留独立层（修正重定基到新版本）。',
                    )
                  }
                >
                  保留独立层
                </Button>
                <Button variant="ghost" size="sm" disabled={busy}
                  onClick={() =>
                    void run(
                      () => resolveConflict(conflict.id, 'adopt_source'),
                      () => '已采用源版本（个人修正层移除）。',
                    )
                  }
                >
                  采用源版本
                </Button>
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

// ---- NEW-330 重定位向导 --------------------------------------------------------

function RelocationSection() {
  return (
    <SubSection id="relocation" label="路径重定位向导（按校验和匹配，不重复导入）">
      {(open) => <RelocationBody open={open} />}
    </SubSection>
  )
}

function RelocationBody({ open }: { open: boolean }) {
  const [rootId, setRootId] = useState('')
  const [newPath, setNewPath] = useState('')
  const [plan, setPlan] = useState<RelocationPlan | null>(null)
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const roots = useQuery({
    queryKey: ['new321-relocation-roots'],
    queryFn: listRootProfiles,
    enabled: open,
  })

  async function runPreview() {
    setBusy(true)
    setError(null)
    setStatus(null)
    setPlan(null)
    try {
      setPlan(await previewRelocation(rootId.trim(), newPath.trim()))
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  async function runApply() {
    if (plan === null) return
    setBusy(true)
    setError(null)
    try {
      const done = await applyRelocation(rootId.trim(), plan.id)
      setStatus(`已接续 ${done.relocatedApplied} 条档案（行身份不变，未重复导入）；档案根已切到新路径。`)
      setPlan(null)
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex flex-col gap-3">
      {roots.isPending ? (
        <NoteText>加载中…</NoteText>
      ) : roots.isError ? (
        <StatusLine tone="error">{errorText(roots.error)}</StatusLine>
      ) : (
        <label className="flex flex-col gap-1">
          <span className="text-xs text-[var(--lumi-text-secondary)]">资料根档案</span>
          <select value={rootId} aria-label="重定位的资料根档案"
            onChange={(e) => setRootId(e.target.value)} className={inputClass}>
            <option value="">选择档案…</option>
            {roots.data.roots.map((root) => (
              <option key={root.id} value={root.id}>
                {root.label}
              </option>
            ))}
          </select>
        </label>
      )}
      <label className="flex flex-col gap-1">
        <span className="text-xs text-[var(--lumi-text-secondary)]">新根目录绝对路径</span>
        <input type="text" value={newPath} aria-label="重定位新根路径"
          onChange={(e) => setNewPath(e.target.value)} className={inputClass} />
      </label>
      <div className="flex flex-wrap gap-2">
        <Button variant="secondary" size="sm" disabled={busy || !rootId.trim() || !newPath.trim()}
          onClick={() => void runPreview()}>
          预览匹配
        </Button>
        {plan !== null && (
          <Button variant="primary" size="sm" disabled={busy} onClick={() => void runApply()}>
            应用重定位
          </Button>
        )}
      </div>
      {error && <StatusLine tone="error">{error}</StatusLine>}
      {status && <StatusLine tone="ok">{status}</StatusLine>}
      {plan !== null && (
        <div className="flex flex-col gap-1" data-new321-relocation-plan="">
          <NoteText>
            按校验和匹配：重定位 {plan.counts.relocated} · 同路径内容已变 {plan.counts.changed} ·
            新增 {plan.counts.fresh} · 消失 {plan.counts.vanished} · 歧义 {plan.counts.ambiguous}（不瞎猜） ·
            冲突 {plan.counts.collision}。预览零写入。
          </NoteText>
          <ul className="ml-4 list-disc text-xs text-[var(--lumi-text-secondary)]">
            {plan.relocated.slice(0, 5).map((m) => (
              <li key={m.to}>{m.from} → {m.to}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
