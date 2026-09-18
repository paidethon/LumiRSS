/** GlossarySection — F21：个人术语本（设置 → 通用）。
 *
 * 用户手工维护的术语与解释：新建/修改/删除/搜索；同词不同含义可并存。
 * 定义是纯文本（客户端转义渲染）。与 AI 无关——不默认调用任何模型。 */

import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'

import {
  createGlossaryTerm,
  deleteGlossaryTerm,
  listGlossary,
} from '../../api/client'
import { Button } from '../ui/Button'

export function GlossarySection() {
  const queryClient = useQueryClient()
  const [filter, setFilter] = useState('')
  const [term, setTerm] = useState('')
  const [definition, setDefinition] = useState('')
  const [error, setError] = useState<string | null>(null)

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
        </div>
      </div>
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
