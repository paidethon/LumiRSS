/** NEW-284 简报缺刊诊断 — 生成入口（可选配方 / 显式范围）+ 失败时
 * stage/missing 如实展示 + 尝试台账（failed → ok 轨迹）。 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import {
  generateBriefing,
  listAttempts,
  listRecipes,
  type ApiError,
  type MissingInput,
} from '../../api/new281'
import {
  NoteText,
  SelectField,
  StatusLine,
  TextField,
  buttonClass,
  errorText,
} from './parts'

export function DiagnosticsPanel() {
  const queryClient = useQueryClient()
  const [recipeId, setRecipeId] = useState('')
  const [rangeFrom, setRangeFrom] = useState('')
  const [rangeTo, setRangeTo] = useState('')
  const [notice, setNotice] = useState<string | null>(null)

  const recipes = useQuery({
    queryKey: ['new281-recipes'],
    queryFn: ({ signal }) => listRecipes(signal),
  })

  const attempts = useQuery({
    queryKey: ['new281-attempts'],
    queryFn: ({ signal }) => listAttempts(signal),
  })

  const generateMutation = useMutation({
    mutationFn: () =>
      generateBriefing({
        ...(recipeId ? { recipeId } : {}),
        ...(rangeFrom && rangeTo ? { rangeFrom, rangeTo } : {}),
      }),
    onSuccess: async (result) => {
      setNotice(
        `已生成草稿「${result.issue.title}」（${result.issue.items.length} 条，规则推荐来源），` +
          `迟到排除 ${result.excludedLate} 条——补齐后重跑即可收进下一期。`,
      )
      await queryClient.invalidateQueries({ queryKey: ['new281-issues'] })
      await queryClient.invalidateQueries({ queryKey: ['new281-attempts'] })
    },
    onError: (error) => {
      // 422 诊断体不是「失败」——如实展示缺失输入与阶段，用户补后重跑。
      if ((error as ApiError).errorType === 'briefing_inputs_missing') {
        const missing = ((error as ApiError).payload.missing as MissingInput[] | undefined) ?? []
        const stage = String((error as ApiError).payload.stage ?? '')
        setNotice(
          `生成停在 ${stage} 阶段：${missing.map((m) => `${m.field}（${m.reason}）`).join('；') || error.message}`,
        )
        void queryClient.invalidateQueries({ queryKey: ['new281-attempts'] })
        return
      }
      setNotice(errorText(error))
    },
  })

  return (
    <div className="flex flex-col gap-3">
      <NoteText>
        生成是确定性装配（零 AI）：按窗口/显式范围 + 栏目规则取文章。失败时这里给出具体缺失输入与执行阶段，
        补输入后重跑——绝不会得到一张空白成功页。
      </NoteText>
      <SelectField
        label="栏目配方（可选，留空 = 单栏目按最新取）"
        value={recipeId}
        onChange={setRecipeId}
        options={[
          { value: '', label: '（不使用配方）' },
          ...(recipes.data?.recipes ?? []).map((recipe) => ({ value: recipe.id, label: recipe.name })),
        ]}
      />
      <div className="grid gap-2 sm:grid-cols-2">
        <TextField label="显式范围起（可选，覆盖窗口）" value={rangeFrom} onChange={setRangeFrom} />
        <TextField label="显式范围止（可选）" value={rangeTo} onChange={setRangeTo} />
      </div>
      <button type="button" className={buttonClass} disabled={generateMutation.isPending} onClick={() => generateMutation.mutate()}>
        生成一期草稿
      </button>
      {notice && (
        <StatusLine tone={generateMutation.isError ? 'info' : 'ok'} data-new281-diagnosis="">
          {notice}
        </StatusLine>
      )}
      <section aria-label="生成尝试台账" className="flex flex-col gap-2">
        <h4 className="text-sm font-medium text-[var(--lumi-text-primary)]">尝试台账</h4>
        {attempts.isError && <StatusLine tone="error">{errorText(attempts.error)}</StatusLine>}
        {attempts.data && attempts.data.count === 0 && <NoteText>还没有生成尝试。</NoteText>}
        {attempts.data?.attempts.map((attempt) => (
          <div
            key={attempt.id}
            data-new281-attempt={attempt.id}
            className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2 py-1.5 text-sm"
          >
            <span
              className={
                attempt.status === 'ok'
                  ? 'text-[var(--lumi-success)]'
                  : 'text-[var(--lumi-danger)]'
              }
            >
              {attempt.status === 'ok' ? '成功' : '失败'}
            </span>{' '}
            <span className="text-xs text-[var(--lumi-text-tertiary)]">
              {attempt.stage} · {attempt.createdAt}
            </span>
            {attempt.missing.length > 0 && (
              <ul className="mt-1 text-xs text-[var(--lumi-text-secondary)]">
                {attempt.missing.map((m) => (
                  <li key={m.field}>
                    {m.field}：{m.reason}
                  </li>
                ))}
              </ul>
            )}
          </div>
        ))}
      </section>
    </div>
  )
}
