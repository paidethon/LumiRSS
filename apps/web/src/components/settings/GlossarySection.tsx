/** GlossarySection — F21：个人术语本（设置 → 通用）。
 *
 * 用户手工维护的术语与解释：新建/修改/删除/搜索；同词不同含义可并存。
 * 定义是纯文本（客户端转义渲染）。与 AI 无关——不默认调用任何模型。 */

import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'

import {
  createGlossaryTerm,
  deleteGlossaryTerm,
  exportGlossaryJson,
  importGlossaryTerms,
  listGlossary,
  parseGlossaryImportText,
} from '../../api/client'
import type { GlossaryImportOutcome } from '../../api/client'
import { Button } from '../ui/Button'

/** F028：导入面板（粘贴 JSON → 预览条数/冲突数 → skip/overwrite 提交）。 */
function GlossaryImportBox({ onDone }: { onDone: () => void }) {
  const [text, setText] = useState('')
  const [mode, setMode] = useState<'skip' | 'overwrite'>('skip')
  const [outcome, setOutcome] = useState<GlossaryImportOutcome | null>(null)
  const [error, setError] = useState<string | null>(null)

  const parsed = text.trim() !== '' ? parseGlossaryImportText(text) : null

  async function submit() {
    if (parsed === null || parsed.terms.length === 0) return
    setError(null)
    try {
      setOutcome(await importGlossaryTerms(parsed.terms, mode))
      onDone()
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : '导入失败，请稍后重试。')
    }
  }

  return (
    <div className="mt-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] p-2.5" data-glossary-import-box="">
      <textarea
        aria-label="粘贴术语 JSON"
        placeholder='{"terms": [{"term": "LLM", "translation": "大语言模型"}]}'
        rows={3}
        value={text}
        onChange={(e) => setText(e.target.value)}
        className="w-full max-w-72 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2.5 py-1.5 text-xs"
      />
      {parsed?.parseError ? (
        <p role="alert" className="mt-1 text-xs text-[var(--lumi-danger)]">
          {parsed.parseError}
        </p>
      ) : null}
      {parsed !== null ? (
        <p className="mt-1 text-xs text-[var(--lumi-text-secondary)]" data-glossary-import-preview="">
          共 {parsed.terms.length} 条可导入
        </p>
      ) : null}
      <div className="mt-1.5 flex items-center gap-2">
        <select
          aria-label="导入模式"
          value={mode}
          onChange={(e) => setMode(e.target.value === 'overwrite' ? 'overwrite' : 'skip')}
          className="min-h-8 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-1.5 text-xs"
        >
          <option value="skip">跳过已有术语</option>
          <option value="overwrite">覆盖已有术语</option>
        </select>
        <Button size="sm" variant="secondary" disabled={parsed === null || parsed.terms.length === 0} onClick={() => void submit()}>
          导入
        </Button>
      </div>
      {error ? (
        <p role="alert" className="mt-1 text-xs text-[var(--lumi-danger)]">
          {error}
        </p>
      ) : null}
      {outcome ? (
        <p className="mt-1 text-xs text-[var(--lumi-text-secondary)]" data-glossary-import-outcome="">
          导入 {outcome.imported} · 跳过 {outcome.skipped} · 覆盖 {outcome.overwritten}
          {outcome.errors.length > 0 ? ` · ${outcome.errors.length} 条错误` : ''}
        </p>
      ) : null}
    </div>
  )
}

export function GlossarySection() {
  const queryClient = useQueryClient()
  const [filter, setFilter] = useState('')
  const [term, setTerm] = useState('')
  const [definition, setDefinition] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [importOpen, setImportOpen] = useState(false)
  const [exportError, setExportError] = useState<string | null>(null)

  const glossary = useQuery({
    queryKey: ['glossary', filter],
    queryFn: ({ signal }) => listGlossary(signal, filter || undefined),
  })

  function invalidate() {
    void queryClient.invalidateQueries({ queryKey: ['glossary'] })
  }

  function submit() {
    setError(null)
    createGlossaryTerm({ term, definition })
      .then(() => {
        setTerm('')
        setDefinition('')
        invalidate()
      })
      .catch((exc: Error) => setError(exc.message))
  }

  const items = glossary.data?.items ?? []

  return (
    <div className="py-3" data-glossary-section>
      <div className="text-sm font-medium text-[var(--lumi-text-primary)]">个人术语本</div>
      <p className="mt-1 text-xs text-[var(--lumi-text-tertiary)]">
        手工维护的术语与解释（纯文本；同词不同含义可并存）。与 AI 无关。
      </p>
      <div className="mt-2 flex flex-col gap-2">
        <input
          aria-label="术语"
          type="text"
          placeholder="术语（≤100 字符）"
          maxLength={100}
          className="w-full max-w-72 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2.5 min-h-9 text-sm text-[var(--lumi-text-primary)]"
          value={term}
          onChange={(e) => setTerm(e.target.value)}
        />
        <textarea
          aria-label="解释"
          placeholder="解释（≤2000 字符）"
          rows={2}
          maxLength={2000}
          className="w-full max-w-72 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2.5 py-1.5 text-sm text-[var(--lumi-text-primary)]"
          value={definition}
          onChange={(e) => setDefinition(e.target.value)}
        />
        <div>
          <Button variant="secondary" size="sm" disabled={!term.trim() || !definition.trim()} onClick={submit}>
            添加术语
          </Button>
          <Button
            variant="ghost"
            size="sm"
            className="ml-2"
            aria-pressed={importOpen}
            onClick={() => setImportOpen((v) => !v)}
          >
            导入
          </Button>
          <Button
            variant="ghost"
            size="sm"
            className="ml-1"
            onClick={() => {
              setExportError(null)
              exportGlossaryJson().catch(() => setExportError('导出失败，请稍后重试。'))
            }}
          >
            导出
          </Button>
        </div>
      </div>
      {importOpen ? <GlossaryImportBox onDone={invalidate} /> : null}
      {exportError ? (
        <p role="alert" className="text-xs text-[var(--lumi-danger)]">
          {exportError}
        </p>
      ) : null}
      {error ? (
        <p role="alert" className="text-xs text-[var(--lumi-danger)]">
          {error}
        </p>
      ) : null}
      <div className="mt-3">
        <input
          aria-label="搜索术语"
          type="search"
          placeholder="搜索术语/解释"
          className="w-full max-w-72 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2.5 min-h-9 text-sm text-[var(--lumi-text-primary)]"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
      </div>
      {glossary.isPending ? null : (
        <ul className="mt-2 flex flex-col divide-y divide-[var(--lumi-separator)]">
          {items.map((item) => (
            <li key={item.id} className="flex items-start justify-between gap-2 py-2">
              <div className="min-w-0">
                <div className="text-sm text-[var(--lumi-text-primary)]">{item.term}</div>
                <div className="text-xs text-[var(--lumi-text-secondary)]">{item.definition}</div>
              </div>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  void deleteGlossaryTerm(item.id).then(invalidate)
                }}
              >
                删除
              </Button>
            </li>
          ))}
          {items.length === 0 ? (
            <li className="py-2 text-xs text-[var(--lumi-text-tertiary)]">还没有术语。</li>
          ) : null}
        </ul>
      )}
    </div>
  )
}
