/** NEW-311/315/316/320 书签侧工具组 — 组合面板（两级情境展开）。
 *
 * - NEW-311 目录导入：选文件 → 预览目录映射与重复链接（零写入）→
 *   勾选目录后确认形成集合（逐条状态由 BFF 落台账）；
 * - NEW-315 链接批量替换：旧域→新域预览逐项变化 → 执行 → 本批可撤销；
 * - NEW-316 意图字段：给书签补「为什么保存/何时使用」+ 按意图筛选；
 * - NEW-320 失效替代关联：为失效书签指定可信新来源 + 理由，变更史
 *   可查（旧链接由服务端保留）。
 *
 * 服务真源在 BFF（routers/new31*.py / new320*.py）；本组件只做真实
 * 调用 + 诚实状态（loading/error/empty），不做客户端转译。
 */

import { useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  addReplacementLink,
  applyLinkReplace,
  confirmBookmarkImport,
  listBookmarkIntents,
  listReplacementLinks,
  previewBookmarkImport,
  previewLinkReplace,
  putBookmarkIntent,
  undoReplaceBatch,
  type ImportPreview,
  type ReplaceChange,
} from '../../api/new311'
import { Button } from '../ui/Button'
import {
  NoteText,
  StatusLine,
  SubSection,
  errorText,
  inputClass,
} from './parts'

export function New311BookmarkTools() {
  const [open, setOpen] = useState(false)
  return (
    <section data-new311-bookmark-tools="">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="min-h-8 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2.5 text-sm font-medium text-[var(--lumi-text-primary)] hover:bg-[var(--lumi-surface-hover)]"
      >
        书签资料工具（{open ? '收起' : '展开'}）
      </button>
      {open && (
        <div className="mt-2 flex flex-col gap-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] p-3">
          <BookmarkImportSection />
          <LinkReplaceSection />
          <IntentSection />
          <ReplacementSection />
        </div>
      )}
    </section>
  )
}

// ---- NEW-311 目录导入 --------------------------------------------------------

function BookmarkImportSection() {
  const [preview, setPreview] = useState<ImportPreview | null>(null)
  const [html, setHtml] = useState('')
  const [selectedFolders, setSelectedFolders] = useState<Set<string>>(new Set())
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<{ imported: number; skipped: number } | null>(null)
  const [busy, setBusy] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  async function loadFile(file: File) {
    const text = await file.text()
    setHtml(text)
    setError(null)
    setResult(null)
    setBusy(true)
    try {
      setPreview(await previewBookmarkImport(text))
    } catch (err) {
      setPreview(null)
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  function toggleFolder(path: string) {
    setSelectedFolders((prev) => {
      const next = new Set(prev)
      if (next.has(path)) next.delete(path)
      else next.add(path)
      return next
    })
  }

  async function confirm() {
    setBusy(true)
    setError(null)
    try {
      const done = await confirmBookmarkImport(html, {
        folders: [...selectedFolders],
        sourceName: '浏览器书签',
      })
      setResult({ imported: done.imported, skipped: done.skipped })
      setPreview(null)
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <SubSection id="import" label="浏览器书签目录导入">
      <input
        ref={fileRef}
        type="file"
        accept=".html,.htm"
        aria-label="选择书签导出文件"
        className="sr-only"
        onChange={(e) => {
          const file = e.target.files?.[0]
          if (file) void loadFile(file)
          e.target.value = ''
        }}
      />
      <Button
        variant="secondary"
        size="sm"
        disabled={busy}
        onClick={() => fileRef.current?.click()}
      >
        选择导出的 bookmarks.html
      </Button>
      {error && <StatusLine tone="error">{error}</StatusLine>}
      {preview && (
        <div className="flex flex-col gap-2" data-new311-import-preview="">
          <NoteText>
            共 {preview.total} 条（有效 {preview.validTotal}）；预览零写入，确认后才导入勾选目录。
          </NoteText>
          <fieldset className="flex flex-col gap-1">
            <legend className="text-xs text-[var(--lumi-text-secondary)]">目录映射</legend>
            {preview.folderMap.map((folder) => (
              <label key={folder.path} className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={selectedFolders.has(folder.path)}
                  onChange={() => toggleFolder(folder.path)}
                  aria-label={`导入目录：${folder.path || '（根）'}`}
                />
                {folder.path || '（根）'}
                <span className="text-[var(--lumi-text-tertiary)]">（{folder.count}）</span>
              </label>
            ))}
          </fieldset>
          {preview.duplicates.length > 0 && (
            <div data-new311-import-duplicates="">
              <NoteText>重复链接 {preview.duplicates.length} 条（默认跳过）：</NoteText>
              <ul className="ml-4 list-disc text-xs text-[var(--lumi-text-secondary)]">
                {preview.duplicates.slice(0, 5).map((dup) => (
                  <li key={dup.url}>
                    {dup.url}（{dup.inFile ? '文件内重复' : ''}
                    {dup.inFile && dup.inLibrary ? ' + ' : ''}
                    {dup.inLibrary ? '库内已有' : ''}）
                  </li>
                ))}
              </ul>
            </div>
          )}
          {preview.invalid.length > 0 && (
            <NoteText>无效条目 {preview.invalid.length} 条将被跳过。</NoteText>
          )}
          <Button variant="primary" size="sm" disabled={busy} onClick={() => void confirm()}>
            确认导入勾选目录
          </Button>
        </div>
      )}
      {result && (
        <StatusLine tone="ok">
          导入完成：新增 {result.imported} 条，跳过 {result.skipped} 条（逐条状态见导入集合台账）。
        </StatusLine>
      )}
    </SubSection>
  )
}

// ---- NEW-315 链接批量替换 ------------------------------------------------------

function LinkReplaceSection() {
  const [fromDomain, setFromDomain] = useState('')
  const [toDomain, setToDomain] = useState('')
  const [changes, setChanges] = useState<ReplaceChange[] | null>(null)
  const [batchId, setBatchId] = useState<string | null>(null)
  const [status, setStatus] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const client = useQueryClient()

  async function runPreview() {
    setBusy(true)
    setError(null)
    setStatus(null)
    try {
      const body = await previewLinkReplace(fromDomain.trim(), toDomain.trim())
      setChanges(body.changes)
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  async function runApply() {
    setBusy(true)
    setError(null)
    try {
      const done = await applyLinkReplace(fromDomain.trim(), toDomain.trim())
      setBatchId(done.id)
      setStatus(`已替换 ${done.changed} 条${done.conflicts.length > 0 ? `，冲突 ${done.conflicts.length} 条（保持原样）` : ''}。本批可撤销。`)
      setChanges(null)
      await client.invalidateQueries()
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  async function runUndo() {
    if (batchId === null) return
    setBusy(true)
    setError(null)
    try {
      const done = await undoReplaceBatch(batchId)
      setStatus(`已撤销本批（恢复 ${done.restored} 条）。`)
      setBatchId(null)
      await client.invalidateQueries()
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <SubSection id="link-replace" label="书签链接批量替换（旧域 → 新域）">
      <div className="flex flex-wrap items-end gap-2">
        <label className="flex flex-col gap-1">
          <span className="text-xs text-[var(--lumi-text-secondary)]">旧域</span>
          <input
            type="text"
            value={fromDomain}
            onChange={(e) => setFromDomain(e.target.value)}
            placeholder="old.example.com"
            aria-label="旧域名"
            className={inputClass}
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-[var(--lumi-text-secondary)]">新域</span>
          <input
            type="text"
            value={toDomain}
            onChange={(e) => setToDomain(e.target.value)}
            placeholder="new.example.com"
            aria-label="新域名"
            className={inputClass}
          />
        </label>
        <Button variant="secondary" size="sm" disabled={busy || !fromDomain || !toDomain} onClick={() => void runPreview()}>
          预览变化
        </Button>
      </div>
      {error && <StatusLine tone="error">{error}</StatusLine>}
      {changes !== null && (
        <div data-new311-replace-preview="">
          {changes.length === 0 ? (
            <NoteText>没有书签命中这个旧域。</NoteText>
          ) : (
            <ul className="ml-4 list-disc text-xs text-[var(--lumi-text-secondary)]">
              {changes.slice(0, 8).map((change) => (
                <li key={change.ref}>
                  {change.before} → {change.after}
                </li>
              ))}
            </ul>
          )}
          {changes.length > 0 && (
            <Button variant="primary" size="sm" disabled={busy} onClick={() => void runApply()}>
              执行替换（{changes.length} 条）
            </Button>
          )}
        </div>
      )}
      {status && <StatusLine tone="ok">{status}</StatusLine>}
      {batchId !== null && (
        <Button variant="secondary" size="sm" disabled={busy} onClick={() => void runUndo()}>
          撤销本批
        </Button>
      )}
    </SubSection>
  )
}

// ---- NEW-316 意图字段 ----------------------------------------------------------

function IntentSection() {
  return (
    <SubSection id="intent" label="书签意图（为什么保存 / 什么时候用）">
      {(open) => <IntentSectionBody open={open} />}
    </SubSection>
  )
}

function IntentSectionBody({ open }: { open: boolean }) {
  const [bookmarkRef, setBookmarkRef] = useState('')
  const [reason, setReason] = useState('')
  const [whenToUse, setWhenToUse] = useState('')
  const [filterWhen, setFilterWhen] = useState('')
  const [status, setStatus] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const bookmarkUuid = bookmarkRef.trim().replace(/^library:/, '')
  // enabled=open：请求只发生在子区真实展开后（折叠零查询）。
  const intents = useQuery({
    queryKey: ['new311-intents', filterWhen],
    queryFn: () => listBookmarkIntents(filterWhen.trim() ? { when: filterWhen.trim() } : {}),
    enabled: open,
  })

  async function save() {
    setBusy(true)
    setError(null)
    setStatus(null)
    try {
      await putBookmarkIntent(bookmarkUuid, { reason, whenToUse })
      setStatus('意图已记录。')
      setReason('')
      setWhenToUse('')
      await intents.refetch()
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
          <span className="text-xs text-[var(--lumi-text-secondary)]">书签 ref（library:…）</span>
          <input
            type="text"
            value={bookmarkRef}
            onChange={(e) => setBookmarkRef(e.target.value)}
            className={inputClass}
          />
        </label>
        <label className="flex flex-1 flex-col gap-1">
          <span className="text-xs text-[var(--lumi-text-secondary)]">为什么保存</span>
          <input
            type="text"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            aria-label="保存理由"
            className={inputClass}
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-[var(--lumi-text-secondary)]">什么时候用</span>
          <input
            type="text"
            value={whenToUse}
            onChange={(e) => setWhenToUse(e.target.value)}
            placeholder="周末 / 工作日…"
            aria-label="使用时机"
            className={inputClass}
          />
        </label>
        <Button
          variant="primary"
          size="sm"
          disabled={busy || !bookmarkUuid.trim() || (!reason.trim() && !whenToUse.trim())}
          onClick={() => void save()}
        >
          记录意图
        </Button>
      </div>
      {status && <StatusLine tone="ok">{status}</StatusLine>}
      {error && <StatusLine tone="error">{error}</StatusLine>}
      <div className="flex items-end gap-2">
        <label className="flex flex-col gap-1">
          <span className="text-xs text-[var(--lumi-text-secondary)]">按用途筛选</span>
          <input
            type="text"
            value={filterWhen}
            onChange={(e) => setFilterWhen(e.target.value)}
            aria-label="意图筛选"
            className={inputClass}
          />
        </label>
      </div>
      {intents.isPending ? (
        <NoteText>加载中…</NoteText>
      ) : intents.isError ? (
        <StatusLine tone="error">{errorText(intents.error)}</StatusLine>
      ) : intents.data.items.length === 0 ? (
        <NoteText>还没有按意图记录的书签。</NoteText>
      ) : (
        <ul className="ml-4 list-disc text-xs text-[var(--lumi-text-secondary)]" data-new311-intent-list="">
          {intents.data.items.map((item) => (
            <li key={item.ref}>
              {item.title}（{item.whenToUse || '—'}：{item.reason || '—'}）
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

// ---- NEW-320 失效替代关联 --------------------------------------------------------

function ReplacementSection() {
  return (
    <SubSection id="replacement" label="失效替代关联（指定可信新来源）">
      {(open) => <ReplacementSectionBody open={open} />}
    </SubSection>
  )
}

function ReplacementSectionBody({ open }: { open: boolean }) {
  const [bookmarkUuid, setBookmarkUuid] = useState('')
  const [newUrl, setNewUrl] = useState('')
  const [reason, setReason] = useState('')
  const [status, setStatus] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const cleanUuid = bookmarkUuid.trim().replace(/^library:/, '')
  const history = useQuery({
    queryKey: ['new311-replacements', cleanUuid],
    queryFn: () => listReplacementLinks(cleanUuid),
    enabled: open && cleanUuid !== '',
  })

  async function save() {
    setBusy(true)
    setError(null)
    setStatus(null)
    try {
      await addReplacementLink(cleanUuid, { newUrl: newUrl.trim(), reason: reason.trim() })
      setStatus('替代关联已记录；旧链接原样保留。')
      setNewUrl('')
      setReason('')
      await history.refetch()
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
          <span className="text-xs text-[var(--lumi-text-secondary)]">书签 ref（library:…）</span>
          <input
            type="text"
            value={bookmarkUuid}
            onChange={(e) => setBookmarkUuid(e.target.value)}
            aria-label="失效书签引用"
            className={inputClass}
          />
        </label>
        <label className="flex flex-1 flex-col gap-1">
          <span className="text-xs text-[var(--lumi-text-secondary)]">新来源 URL</span>
          <input
            type="url"
            value={newUrl}
            onChange={(e) => setNewUrl(e.target.value)}
            placeholder="https://…"
            aria-label="新来源地址"
            className={inputClass}
          />
        </label>
        <label className="flex flex-1 flex-col gap-1">
          <span className="text-xs text-[var(--lumi-text-secondary)]">替换理由</span>
          <input
            type="text"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            aria-label="替换理由"
            className={inputClass}
          />
        </label>
        <Button
          variant="primary"
          size="sm"
          disabled={busy || cleanUuid === '' || !newUrl.trim() || !reason.trim()}
          onClick={() => void save()}
        >
          记录替代
        </Button>
      </div>
      {status && <StatusLine tone="ok">{status}</StatusLine>}
      {error && <StatusLine tone="error">{error}</StatusLine>}
      {cleanUuid !== '' && history.isPending && <NoteText>加载中…</NoteText>}
      {cleanUuid !== '' && history.isError && (
        <StatusLine tone="error">{errorText(history.error)}</StatusLine>
      )}
      {cleanUuid !== '' && history.data && (
        <ul className="ml-4 list-disc text-xs text-[var(--lumi-text-secondary)]" data-new311-replacement-history="">
          <li>旧链接（保留）：{history.data.oldUrl ?? '—'}</li>
          {history.data.history.map((item) => (
            <li key={item.id}>
              {item.current ? '当前生效' : '历史'}：{item.newUrl}——{item.reason}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
