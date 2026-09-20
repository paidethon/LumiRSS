/** F020 本地 Markdown 批量入库 —— 文件选择 → 预览 → 确认导入 → 逐项结果。
 *
 * 预览零写入（读取文件为纯客户端行为，不发请求）；导入仅确认后调用
 * /library/notes/import（BFF 逐文件校验：≤200KB/文件、≤50/批、幂等）。
 * 部分失败诚实展示逐项结果；导入成功后失效笔记列表缓存。 */

import { useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { FileUp, Loader2 } from 'lucide-react'
import { importLumiNotes } from '../api/client'
import { Button } from './ui/Button'

const MAX_FILE_BYTES = 200 * 1024
const MAX_BATCH_FILES = 50

interface DraftFile {
  name: string
  size: number
  content: string
  tooLarge: boolean
}

interface ResultItem {
  name: string
  ok: boolean
  reason: string | null
}

export function MarkdownImportPanel({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient()
  const inputRef = useRef<HTMLInputElement | null>(null)
  const [drafts, setDrafts] = useState<DraftFile[]>([])
  const [results, setResults] = useState<ResultItem[] | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function selectFiles(files: FileList | null) {
    setError(null)
    setResults(null)
    if (files === null || files.length === 0) return
    if (files.length > MAX_BATCH_FILES) {
      setError(`每批最多 ${MAX_BATCH_FILES} 个文件。`)
      return
    }
    const list: DraftFile[] = []
    let pending = files.length
    const maybeFinish = () => {
      if (pending === 0) setDrafts([...list])
    }
    for (const file of Array.from(files)) {
      const reader = new FileReader()
      reader.onload = () => {
        const text = typeof reader.result === 'string' ? reader.result : ''
        // 非法 UTF-8 在 FileReader readAsText 中表现为替换字符，仍可预览；
        // 入库由后端最终校验。
        list.push({
          name: file.name,
          size: file.size,
          content: text,
          tooLarge: file.size > MAX_FILE_BYTES,
        })
        pending -= 1
        maybeFinish()
      }
      reader.onerror = () => {
        pending -= 1
        maybeFinish()
      }
      reader.readAsText(file)
    }
  }

  async function confirmImport() {
    if (busy || drafts.length === 0) return
    setBusy(true)
    setError(null)
    try {
      const result = await importLumiNotes({
        files: drafts.map((d) => ({ name: d.name, content: d.content })),
      })
      setResults(
        result.items.map((item) => ({
          name: item.name,
          ok: item.ok,
          reason: item.reason ?? null,
        })),
      )
      await queryClient.invalidateQueries({ queryKey: ['lumi-notes'] })
    } catch (e) {
      setError(e instanceof Error ? e.message : '导入失败，请稍后重试。')
    } finally {
      setBusy(false)
    }
  }

  const importable = drafts.filter((d) => !d.tooLarge).length

  return (
    <section
      aria-label="导入 Markdown"
      data-testid="markdown-import-panel"
      className="mb-3 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-3"
    >
      <h3 className="flex items-center gap-1.5 text-sm font-semibold text-[var(--lumi-text-primary)]">
        <FileUp aria-hidden className="size-4" />
        导入 Markdown
      </h3>
      <input
        ref={inputRef}
        type="file"
        accept=".md,.markdown,text/markdown"
        multiple
        aria-label="选择 Markdown 文件（可多选）"
        className="sr-only"
        onChange={(e) => {
          selectFiles(e.target.files)
          e.target.value = ''
        }}
      />
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <Button size="sm" variant="secondary" onClick={() => inputRef.current?.click()}>
          选择文件（.md，可多选）
        </Button>
        <Button
          size="sm"
          variant="primary"
          disabled={busy || importable === 0}
          onClick={() => void confirmImport()}
        >
          {busy ? (
            <>
              <Loader2 aria-hidden className="size-4 animate-spin" />
              导入中…
            </>
          ) : (
            `确认导入（${importable}）`
          )}
        </Button>
        <Button size="sm" variant="ghost" onClick={onClose}>
          收起
        </Button>
        <span className="text-xs text-[var(--lumi-text-tertiary)]">
          预览不发请求；单文件 ≤200KB，每批 ≤50 个；同内容自动跳过。
        </span>
      </div>
      {error !== null && (
        <p role="alert" className="mt-2 text-xs text-[var(--lumi-danger)]">
          {error}
        </p>
      )}
      {drafts.length > 0 && results === null && (
        <table className="mt-2 w-full text-xs">
          <thead>
            <tr className="text-left text-[var(--lumi-text-tertiary)]">
              <th className="py-1 pr-2 font-medium">文件名</th>
              <th className="py-1 pr-2 font-medium">标题</th>
              <th className="py-1 pr-2 font-medium">大小</th>
              <th className="py-1 font-medium">状态</th>
            </tr>
          </thead>
          <tbody>
            {drafts.map((d) => (
              <tr key={d.name} className="border-t border-[var(--lumi-separator)]">
                <td className="max-w-40 truncate py-1 pr-2">{d.name}</td>
                <td className="max-w-40 truncate py-1 pr-2">
                  {d.name.replace(/\.(md|markdown)$/i, '')}
                </td>
                <td className="py-1 pr-2">{(d.size / 1024).toFixed(1)} KB</td>
                <td className="py-1">
                  {d.tooLarge ? (
                    <span className="text-[var(--lumi-danger)]">超过 200KB</span>
                  ) : (
                    <span className="text-[var(--lumi-text-secondary)]">将导入</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {results !== null && (
        <div className="mt-2">
          <p role="status" className="text-xs text-[var(--lumi-text-secondary)]">
            导入完成：成功 {results.filter((r) => r.ok).length} / 失败{' '}
            {results.filter((r) => !r.ok).length}
            （同内容自动跳过）
          </p>
          <ul className="mt-1 flex flex-col gap-0.5">
            {results.map((r) => (
              <li key={r.name} className="truncate text-xs">
                {r.name}
                {' · '}
                {r.ok ? (
                  <span className="text-[var(--lumi-accent-text)]">
                    {r.reason === 'duplicate' ? '跳过（内容已存在）' : '已导入'}
                  </span>
                ) : (
                  <span className="text-[var(--lumi-danger)]">{r.reason ?? '失败'}</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  )
}
