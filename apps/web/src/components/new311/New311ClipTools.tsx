/** NEW-312/313/317/318/319 剪藏侧工具组 — 组合面板（两级情境展开）。
 *
 * - NEW-312 选区剪藏包：用户粘贴选中文字（空行分段）+ 页面 URL/标题，
 *   零抓取保存选区包；
 * - NEW-313 候选对照：对已有剪藏请求同一次抓取的双候选，选择更完整
 *   版本（服务端只写修订槽，原版与笔记锚点不动）；
 * - NEW-317 重复合并：列出同页候选组，选择保留侧与元数据策略后合并；
 * - NEW-318 图片选择器：图片清单（体积如实展示，未知=—）→ 勾选后
 *   保存（未勾选的图片服务端一个字节不留）；
 * - NEW-319 重新提取：对已有剪藏发起新提取，done 后由用户显式应用。
 *
 * 服务真源在 BFF；fetch 类操作失败 → 原样透出 BFF message（诚实）。
 */

import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  applyReextract,
  chooseExtractCandidate,
  compareExtractCandidates,
  createCuratedClip,
  createSelectionPackage,
  fetchImageManifest,
  listDuplicateGroups,
  listReextractions,
  mergeClips,
  requestReextract,
  type ExtractCompare,
  type ImageManifest,
} from '../../api/new311'
import { Button } from '../ui/Button'
import {
  NoteText,
  StatusLine,
  SubSection,
  errorText,
  inputClass,
} from './parts'

function refToUuid(ref: string): string {
  return ref.trim().replace(/^library:/, '')
}

export function New311ClipTools() {
  const [open, setOpen] = useState(false)
  return (
    <section data-new311-clip-tools="">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="min-h-8 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2.5 text-sm font-medium text-[var(--lumi-text-primary)] hover:bg-[var(--lumi-surface-hover)]"
      >
        剪藏资料工具（{open ? '收起' : '展开'}）
      </button>
      {open && (
        <div className="mt-2 flex flex-col gap-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] p-3">
          <SelectionSection />
          <ExtractCompareSection />
          <MergeSection />
          <ImagePickerSection />
          <ReextractSection />
        </div>
      )}
    </section>
  )
}

// ---- NEW-312 选区剪藏包 --------------------------------------------------------

function SelectionSection() {
  const [url, setUrl] = useState('')
  const [pageTitle, setTitle] = useState('')
  const [text, setText] = useState('')
  const [clipRef, setClipRef] = useState('')
  const [status, setStatus] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function save() {
    setBusy(true)
    setError(null)
    setStatus(null)
    const selections = text
      .split(/\n\s*\n/)
      .map((chunk) => chunk.trim())
      .filter(Boolean)
      .map((chunk) => ({ text: chunk }))
    try {
      const created = await createSelectionPackage({
        url: url.trim(),
        pageTitle: pageTitle.trim(),
        selections,
        clipRef: clipRef.trim() || null,
      })
      setStatus(`选区剪藏包已保存：${created.selections.length} 段选区（未自动抓取整页）。`)
      setText('')
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <SubSection id="selection" label="网页选区剪藏包">
      <label className="flex flex-col gap-1">
        <span className="text-xs text-[var(--lumi-text-secondary)]">页面 URL</span>
        <input
          type="url"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://…"
          aria-label="选区页面地址"
          className={inputClass}
        />
      </label>
      <label className="flex flex-col gap-1">
        <span className="text-xs text-[var(--lumi-text-secondary)]">页面标题（可选）</span>
        <input
          type="text"
          value={pageTitle}
          onChange={(e) => setTitle(e.target.value)}
          aria-label="选区页面标题"
          className={inputClass}
        />
      </label>
      <label className="flex flex-col gap-1">
        <span className="text-xs text-[var(--lumi-text-secondary)]">
          选中文字（空行分段，每段一段选区）
        </span>
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={4}
          aria-label="选中文字"
          className={inputClass}
        />
      </label>
      <label className="flex flex-col gap-1">
        <span className="text-xs text-[var(--lumi-text-secondary)]">挂接已有剪藏 ref（可选）</span>
        <input
          type="text"
          value={clipRef}
          onChange={(e) => setClipRef(e.target.value)}
          placeholder="library:…"
          aria-label="挂接剪藏引用"
          className={inputClass}
        />
      </label>
      <Button
        variant="primary"
        size="sm"
        disabled={busy || !url.trim() || text.trim() === ''}
        onClick={() => void save()}
      >
        保存选区（不抓整页）
      </Button>
      {status && <StatusLine tone="ok">{status}</StatusLine>}
      {error && <StatusLine tone="error">{error}</StatusLine>}
    </SubSection>
  )
}

// ---- NEW-313 候选对照 -----------------------------------------------------------

function ExtractCompareSection() {
  const [clipRef, setClipRef] = useState('')
  const [compare, setCompare] = useState<ExtractCompare | null>(null)
  const [status, setStatus] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const cleanUuid = refToUuid(clipRef)

  async function runCompare() {
    setBusy(true)
    setError(null)
    setStatus(null)
    try {
      setCompare(await compareExtractCandidates(cleanUuid))
    } catch (err) {
      setCompare(null)
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  async function choose(candidateId: string) {
    if (cleanUuid === '') return
    setBusy(true)
    try {
      const done = await chooseExtractCandidate(cleanUuid, candidateId)
      setStatus(done.note)
      setCompare(null)
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <SubSection id="extract-compare" label="剪藏正文候选对照">
      <label className="flex flex-col gap-1">
        <span className="text-xs text-[var(--lumi-text-secondary)]">剪藏 ref（library:…）</span>
        <input
          type="text"
          value={clipRef}
          onChange={(e) => setClipRef(e.target.value)}
          aria-label="对照剪藏引用"
          className={inputClass}
        />
      </label>
      <Button
        variant="secondary"
        size="sm"
        disabled={busy || cleanUuid === ''}
        onClick={() => void runCompare()}
      >
        抓取并对照两种提取
      </Button>
      {error && <StatusLine tone="error">{error}</StatusLine>}
      {compare && (
        <div className="flex flex-col gap-2" data-new311-extract-compare="">
          {compare.candidates.map((candidate) => (
            <div key={candidate.id} className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-2">
              <p className="text-sm font-medium text-[var(--lumi-text-primary)]">
                {candidate.strategy === 'article' ? '评分提取' : '保真全文'}（{candidate.charCount} 字）
              </p>
              <p className="mt-1 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
                {candidate.preview || '（无可预览文本）'}
              </p>
              <Button
                variant="secondary"
                size="sm"
                className="mt-1.5"
                disabled={busy}
                onClick={() => void choose(candidate.id)}
              >
                选这个版本
              </Button>
            </div>
          ))}
          <NoteText>{compare.honestyNote}</NoteText>
        </div>
      )}
      {status && <StatusLine tone="ok">{status}</StatusLine>}
    </SubSection>
  )
}

// ---- NEW-317 重复合并 -------------------------------------------------------------

function MergeSection() {
  return (
    <SubSection id="merge" label="剪藏重复合并">
      {(open) => <MergeSectionBody open={open} />}
    </SubSection>
  )
}

function MergeSectionBody({ open }: { open: boolean }) {
  const [keepRef, setKeepRef] = useState<string | null>(null)
  const [mergeRefs, setMergeRefs] = useState<Set<string>>(new Set())
  const [metaPolicy, setMetaPolicy] = useState<'kept' | 'newest'>('kept')
  const [status, setStatus] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  // enabled=open：分组查询只在子区真实展开后发起（折叠零查询）。
  const groups = useQuery({
    queryKey: ['new311-duplicate-groups'],
    queryFn: listDuplicateGroups,
    enabled: open,
  })
  const client = useQueryClient()

  function toggleMerge(ref: string) {
    setMergeRefs((prev) => {
      const next = new Set(prev)
      if (next.has(ref)) next.delete(ref)
      else next.add(ref)
      return next
    })
  }

  async function runMerge() {
    if (keepRef === null || mergeRefs.size === 0) return
    setBusy(true)
    setError(null)
    try {
      const done = await mergeClips({
        keepRef,
        mergeRefs: [...mergeRefs],
        metaPolicy,
      })
      setStatus(
        `合并完成：选段迁移 ${done.carriedSelections} 段；被并入剪藏进入回收站。`,
      )
      setMergeRefs(new Set())
      setKeepRef(null)
      await groups.refetch()
      await client.invalidateQueries()
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex flex-col gap-3">
      {groups.isPending ? (
        <NoteText>加载中…</NoteText>
      ) : groups.isError ? (
        <StatusLine tone="error">{errorText(groups.error)}</StatusLine>
      ) : groups.data.groups.length === 0 ? (
        <NoteText>没有同页重复的剪藏。</NoteText>
      ) : (
        groups.data.groups.map((group) => (
          <fieldset key={group.key} className="flex flex-col gap-1" data-new311-merge-group="">
            <legend className="text-xs text-[var(--lumi-text-secondary)]">{group.key}</legend>
            {group.items.map((item) => (
              <label key={item.ref} className="flex items-center gap-2 text-sm">
                <input
                  type="radio"
                  name={`keep-${group.key}`}
                  checked={keepRef === item.ref}
                  onChange={() => setKeepRef(item.ref)}
                  aria-label={`保留：${item.title}`}
                />
                <span className="min-w-0 flex-1 truncate">{item.title}</span>
                <input
                  type="checkbox"
                  checked={mergeRefs.has(item.ref)}
                  onChange={() => toggleMerge(item.ref)}
                  aria-label={`并入：${item.title}`}
                />
              </label>
            ))}
          </fieldset>
        ))
      )}
      {groups.data && groups.data.groups.length > 0 && (
        <div className="flex items-end gap-2">
          <label className="flex flex-col gap-1">
            <span className="text-xs text-[var(--lumi-text-secondary)]">元数据</span>
            <select
              value={metaPolicy}
              onChange={(e) => setMetaPolicy(e.target.value as 'kept' | 'newest')}
              aria-label="合并元数据策略"
              className={inputClass}
            >
              <option value="kept">保留侧标题</option>
              <option value="newest">最新剪藏标题</option>
            </select>
          </label>
          <Button
            variant="primary"
            size="sm"
            disabled={busy || keepRef === null || mergeRefs.size === 0}
            onClick={() => void runMerge()}
          >
            合并所选（{mergeRefs.size}）
          </Button>
        </div>
      )}
      {status && <StatusLine tone="ok">{status}</StatusLine>}
      {error && <StatusLine tone="error">{error}</StatusLine>}
      <NoteText>单选 = 保留侧；勾选 = 并入。选段与修订版本会迁入保留侧。</NoteText>
    </div>
  )
}

// ---- NEW-318 图片选择器 -------------------------------------------------------------

function ImagePickerSection() {
  const [url, setUrl] = useState('')
  const [manifest, setManifest] = useState<ImageManifest | null>(null)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [status, setStatus] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const client = useQueryClient()

  function formatBytes(bytes: number | null): string {
    if (bytes === null) return '体积未知'
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
    return `${Math.round(bytes / (1024 * 1024))} MB`
  }

  async function loadManifest() {
    setBusy(true)
    setError(null)
    setStatus(null)
    try {
      const body = await fetchImageManifest(url.trim())
      setManifest(body)
      setSelected(new Set())
    } catch (err) {
      setManifest(null)
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  async function saveSelected() {
    if (manifest === null) return
    setBusy(true)
    try {
      const done = await createCuratedClip(url.trim(), [...selected])
      setStatus(
        `已保存剪藏（${done.selectedCount} 张图${done.unknownSelections.length > 0 ? `，${done.unknownSelections.length} 个勾选不在清单中` : ''}）。`,
      )
      setManifest(null)
      await client.invalidateQueries()
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <SubSection id="image-picker" label="剪藏图片选择器">
      <div className="flex flex-wrap items-end gap-2">
        <label className="flex flex-1 flex-col gap-1">
          <span className="text-xs text-[var(--lumi-text-secondary)]">页面 URL</span>
          <input
            type="url"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            aria-label="图片清单页面地址"
            className={inputClass}
          />
        </label>
        <Button variant="secondary" size="sm" disabled={busy || !url.trim()} onClick={() => void loadManifest()}>
          列出可用图片
        </Button>
      </div>
      {error && <StatusLine tone="error">{error}</StatusLine>}
      {manifest && (
        <div className="flex flex-col gap-2" data-new311-image-manifest="">
          {manifest.images.length === 0 ? (
            <NoteText>页面上没有可用图片。</NoteText>
          ) : (
            manifest.images.map((image) => (
              <label key={image.src} className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={selected.has(image.src)}
                  onChange={() =>
                    setSelected((prev) => {
                      const next = new Set(prev)
                      if (next.has(image.src)) next.delete(image.src)
                      else next.add(image.src)
                      return next
                    })
                  }
                  aria-label={`选择图片：${image.alt || image.src}`}
                />
                <span className="min-w-0 flex-1 truncate">{image.alt || image.src}</span>
                <span className="text-xs text-[var(--lumi-text-tertiary)]">
                  {formatBytes(image.bytes)}
                </span>
              </label>
            ))
          )}
          <NoteText>{manifest.honestyNote}</NoteText>
          <Button variant="primary" size="sm" disabled={busy} onClick={() => void saveSelected()}>
            保存勾选的图片（{selected.size}）
          </Button>
        </div>
      )}
      {status && <StatusLine tone="ok">{status}</StatusLine>}
    </SubSection>
  )
}

// ---- NEW-319 重新提取 -----------------------------------------------------------------

function ReextractSection() {
  return (
    <SubSection id="reextract" label="资料重新提取">
      {(open) => <ReextractSectionBody open={open} />}
    </SubSection>
  )
}

function ReextractSectionBody({ open }: { open: boolean }) {
  const [clipRef, setClipRef] = useState('')
  const [status, setStatus] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const cleanUuid = refToUuid(clipRef)
  const requests = useQuery({
    queryKey: ['new311-reextract', cleanUuid],
    queryFn: () => listReextractions(cleanUuid),
    enabled: open && cleanUuid !== '',
  })
  const client = useQueryClient()

  async function requestNew() {
    setBusy(true)
    setError(null)
    setStatus(null)
    try {
      const done = await requestReextract(cleanUuid)
      setStatus(
        done.status === 'done'
          ? `新提取完成（${done.charCount} 字），请确认后应用。`
          : done.status === 'failed'
            ? `新提取失败：${done.error ?? '未知原因'}（旧版本不受影响）。`
            : '新提取进行中…',
      )
      await requests.refetch()
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  async function apply(requestId: string) {
    setBusy(true)
    try {
      const done = await applyReextract(cleanUuid, requestId)
      setStatus(done.note)
      await requests.refetch()
      await client.invalidateQueries()
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
          <span className="text-xs text-[var(--lumi-text-secondary)]">剪藏 ref（library:…）</span>
          <input
            type="text"
            value={clipRef}
            onChange={(e) => setClipRef(e.target.value)}
            aria-label="重提取剪藏引用"
            className={inputClass}
          />
        </label>
        <Button variant="secondary" size="sm" disabled={busy || cleanUuid === ''} onClick={() => void requestNew()}>
          发起一次新提取
        </Button>
      </div>
      {status && <StatusLine tone="ok">{status}</StatusLine>}
      {error && <StatusLine tone="error">{error}</StatusLine>}
      {cleanUuid !== '' && requests.isPending && <NoteText>加载中…</NoteText>}
      {cleanUuid !== '' && requests.isError && (
        <StatusLine tone="error">{errorText(requests.error)}</StatusLine>
      )}
      {cleanUuid !== '' && requests.data && requests.data.requests.length === 0 && (
        <NoteText>还没有重提取请求。</NoteText>
      )}
      {cleanUuid !== '' &&
        requests.data &&
        requests.data.requests.map((request) => (
          <div
            key={request.id}
            data-new311-reextract-row=""
            className="flex items-center justify-between gap-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-2 text-sm"
          >
            <span className="min-w-0 flex-1 truncate text-[var(--lumi-text-secondary)]">
              {request.status === 'done'
                ? `新版本：${request.title}（${request.charCount} 字）`
                : request.status === 'failed'
                  ? `失败：${request.error ?? ''}`
                  : '进行中…'}
            </span>
            {request.status === 'done' && !request.applied && (
              <Button variant="secondary" size="sm" disabled={busy} onClick={() => void apply(request.id)}>
                应用新版本
              </Button>
            )}
            {request.applied && <span className="text-xs text-[var(--lumi-text-tertiary)]">已应用</span>}
          </div>
        ))}
    </div>
  )
}
