/** SynonymsControls — F078 检索同义词（SearchPage 设置区）。
 *
 * 「扩展」开关（本次关闭立即恢复原结果；持久化在 localStorage）+
 * 同义词管理对话框（增删）。 */

import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { BookA } from 'lucide-react'
import {
  createSynonym,
  deleteSynonym,
  listSynonyms,
} from '../api/client'
import { Button } from './ui/Button'
import { Dialog } from './ui/Dialog'
import { Switch } from './ui/Switch'

const TOGGLE_KEY = 'lumirss-synonym-expand'

/** 读取扩展开关（客户端默认开）。 */
export function readExpandSynonyms(): boolean {
  if (typeof localStorage === 'undefined') return true
  return localStorage.getItem(TOGGLE_KEY) !== 'false'
}

export function SynonymsControls({
  expanded,
  onToggle,
}: {
  expanded: boolean
  onToggle: (checked: boolean) => void
}) {
  const [_, setLocalExpanded] = useState(true)
  const [managerOpen, setManagerOpen] = useState(false)
  const [term, setTerm] = useState('')
  const [expansions, setExpansions] = useState('')
  const queryClient = useQueryClient()

  useEffect(() => {
    setLocalExpanded(readExpandSynonyms())
  }, [])

  const toggle = (checked: boolean) => {
    onToggle(checked)
    try {
      localStorage.setItem(TOGGLE_KEY, checked ? 'true' : 'false')
    } catch {
      /* 忽略 */
    }
    void queryClient.invalidateQueries({ queryKey: ['search'] })
  }

  const list = useQuery({
    queryKey: ['search-synonyms'],
    queryFn: listSynonyms,
    enabled: managerOpen,
  })
  const create = useMutation({
    mutationFn: () =>
      createSynonym(
        term.trim(),
        expansions.split(/[|,，]/).map((x) => x.trim()).filter((x) => x !== ''),
      ),
    onSuccess: async () => {
      setTerm('')
      setExpansions('')
      await queryClient.invalidateQueries({ queryKey: ['search-synonyms'] })
    },
  })
  const remove = useMutation({
    mutationFn: (id: string) => deleteSynonym(id),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['search-synonyms'] })
    },
  })

  return (
    <span data-lumi-synonym-controls="" className="inline-flex items-center gap-1.5">
      <Switch
        checked={expanded}
        onCheckedChange={toggle}
        label="同义词扩展"
      />
      <span className="text-xs text-[var(--lumi-text-secondary)]">扩展</span>
      <Button size="sm" variant="ghost" onClick={() => setManagerOpen(true)}>
        <BookA aria-hidden className="size-3.5" />
        同义词
      </Button>
      <Dialog open={managerOpen} onClose={() => setManagerOpen(false)} title="同义词管理" panelClassName="max-w-md">
        <div className="flex flex-col gap-3 text-xs">
          <div className="flex flex-wrap items-end gap-2">
            <label className="flex flex-col gap-1 text-[var(--lumi-text-secondary)]">
              词
              <input
                aria-label="同义词词"
                value={term}
                onChange={(e) => setTerm(e.target.value)}
                maxLength={50}
                className="w-32 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1.5 text-sm"
              />
            </label>
            <label className="flex flex-1 flex-col gap-1 text-[var(--lumi-text-secondary)]">
              扩展词（用 | 分隔，≤8 个）
              <input
                aria-label="扩展词"
                value={expansions}
                onChange={(e) => setExpansions(e.target.value)}
                placeholder="大模型|LLM2"
                className="w-full rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1.5 text-sm"
              />
            </label>
            <Button
              size="sm"
              variant="primary"
              disabled={create.isPending || term.trim() === '' || expansions.trim() === ''}
              onClick={() => create.mutate()}
            >
              添加
            </Button>
          </div>
          {(list.data?.items ?? []).length === 0 ? (
            <p className="text-[var(--lumi-text-tertiary)]">还没有同义词。添加后，搜索命中词时会 OR 并入扩展词（单层展开）。</p>
          ) : (
            <ul className="flex flex-col gap-1">
              {(list.data?.items ?? []).map((s) => (
                <li
                  key={s.id}
                  className="flex items-center gap-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2 py-1.5"
                >
                  <span className="font-medium text-[var(--lumi-text-primary)]">{s.term}</span>
                  <span className="text-[var(--lumi-text-tertiary)]">→ {s.expansions.join(' | ')}</span>
                  <span className="flex-1" />
                  {!s.enabled && <span className="text-[11px] text-[var(--lumi-text-tertiary)]">已停用</span>}
                  <Button size="sm" variant="ghost" disabled={remove.isPending} onClick={() => remove.mutate(s.id)}>
                    删除
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </Dialog>
    </span>
  )
}
