/** NEW-269 语言识别纠正 — 某文/某源识别语言的显式更正（BCP-47 短代码）；
 * 只影响其后的新生成，既有缓存译文原样展示（已产生结果不悄悄改变）。 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import {
  deleteLanguageOverride,
  getEntryLanguageOverride,
  listLanguageOverrides,
  setLanguageOverride,
} from '../../api/new261'
import { Button } from '../ui/Button'
import { NoticeLine } from './parts'

const LANGUAGE_MAX = 12

export function LanguageOverridePanel({ entryRef, feedUrl }: { entryRef: string; feedUrl: string | null }) {
  const queryClient = useQueryClient()
  const overridesQuery = useQuery({
    queryKey: ['new269-language-overrides'],
    queryFn: ({ signal }) => listLanguageOverrides(signal),
  })
  const entryQuery = useQuery({
    queryKey: ['new269-entry-override', entryRef],
    queryFn: ({ signal }) => getEntryLanguageOverride(entryRef, signal),
  })
  const [scope, setScope] = useState<'entry' | 'source'>('entry')
  const [language, setLanguage] = useState('')
  const [notice, setNotice] = useState<string | null>(null)

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['new269-language-overrides'] })
    void queryClient.invalidateQueries({ queryKey: ['new269-entry-override', entryRef] })
  }

  const setMutation = useMutation({
    mutationFn: () => setLanguageOverride(scope, scope === 'entry' ? entryRef : (feedUrl ?? ''), language.trim()),
    onSuccess: (item) => {
      setNotice(`已更正：${item.scope === 'entry' ? '这篇文章' : '整个来源'}其后新生成按 ${item.language} 处理；既有译文原样保留。`)
      setLanguage('')
      invalidate()
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : '更正失败'),
  })
  const removeMutation = useMutation({
    mutationFn: (input: { scope: 'entry' | 'source'; refKey: string }) =>
      deleteLanguageOverride(input.scope, input.refKey),
    onSuccess: () => {
      setNotice('已撤销更正，回到自动识别。')
      invalidate()
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : '撤销失败'),
  })

  const overrides = overridesQuery.data?.overrides ?? []
  const effective = entryQuery.data?.language ?? null

  return (
    <div className="flex flex-col gap-2">
      <p className="text-xs leading-relaxed text-[var(--lumi-text-tertiary)]">
        当前生效识别语言：{effective ?? '自动识别（无更正）'}。更正只影响其后新生成，已产生的译文不会悄悄改变。
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <label className="text-xs text-[var(--lumi-text-secondary)]">
          范围
          <select
            value={scope}
            onChange={(event) => setScope(event.target.value === 'source' ? 'source' : 'entry')}
            aria-label="更正范围"
            className="ml-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-1.5 py-1 text-xs"
          >
            <option value="entry">仅这篇文章</option>
            <option value="source">整个来源{feedUrl ? '' : '（本篇无来源地址，不可选）'}</option>
          </select>
        </label>
        <input
          type="text"
          value={language}
          maxLength={LANGUAGE_MAX}
          onChange={(event) => setLanguage(event.target.value)}
          placeholder="如 en、zh、pt-BR"
          aria-label="更正为的语言代码"
          className="w-32 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-xs"
        />
        <Button
          size="sm"
          variant="secondary"
          disabled={language.trim() === '' || (scope === 'source' && !feedUrl) || setMutation.isPending}
          onClick={() => setMutation.mutate()}
        >
          登记更正
        </Button>
      </div>

      {overrides.length > 0 && (
        <ul className="flex flex-col gap-1 text-xs text-[var(--lumi-text-secondary)]">
          {overrides.map((item) => (
            <li key={`${item.scope}:${item.refKey}`} className="flex flex-wrap items-center gap-2 rounded-[var(--lumi-radius-sm)] bg-[var(--lumi-surface-hover)] p-1.5">
              <span>
                {item.scope === 'entry' ? '文章' : '来源'} · {item.refKey.length > 48 ? `${item.refKey.slice(0, 48)}…` : item.refKey} →{' '}
                <span className="font-medium text-[var(--lumi-text-primary)]">{item.language}</span>
              </span>
              <Button
                size="sm"
                variant="ghost"
                disabled={removeMutation.isPending}
                onClick={() => removeMutation.mutate({ scope: item.scope, refKey: item.refKey })}
              >
                撤销
              </Button>
            </li>
          ))}
        </ul>
      )}
      {notice !== null && <NoticeLine tone={notice.includes('失败') ? 'error' : 'success'}>{notice}</NoticeLine>}
    </div>
  )
}
