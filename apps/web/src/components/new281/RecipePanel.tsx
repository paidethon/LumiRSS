/** NEW-286 简报栏目配方 — 栏目顺序 + 字数预算 + 选择规则的可复用配方。 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { createRecipe, deleteRecipe, listRecipes } from '../../api/new281'
import {
  NoteText,
  SelectField,
  StatusLine,
  TextField,
  buttonClass,
  errorText,
  secondaryButtonClass,
} from './parts'

const EMPTY_SECTION = { key: 'top', label: '要闻', rule: 'starred' as const, budget: 400, feedUrl: '' }

export function RecipePanel() {
  const queryClient = useQueryClient()
  const [name, setName] = useState('')
  const [key, setKey] = useState(EMPTY_SECTION.key)
  const [label, setLabel] = useState(EMPTY_SECTION.label)
  const [rule, setRule] = useState<string>(EMPTY_SECTION.rule)
  const [budget, setBudget] = useState(String(EMPTY_SECTION.budget))
  const [feedUrl, setFeedUrl] = useState('')
  const [notice, setNotice] = useState<string | null>(null)

  const recipes = useQuery({
    queryKey: ['new281-recipes'],
    queryFn: ({ signal }) => listRecipes(signal),
  })

  const invalidate = async () => {
    await queryClient.invalidateQueries({ queryKey: ['new281-recipes'] })
  }

  const createMutation = useMutation({
    mutationFn: () =>
      createRecipe(name.trim(), [
        {
          key: key.trim(),
          label: label.trim(),
          rule: rule as 'starred' | 'recent' | 'feed',
          budget: Number(budget),
          feedUrl: feedUrl.trim(),
        },
      ]),
    onSuccess: async (recipe) => {
      setNotice(`配方「${recipe.name}」已保存（1 个栏目；下一期生成可直接使用，建稿后仍可微调）。`)
      setName('')
      await invalidate()
    },
    onError: (error) => setNotice(errorText(error)),
  })

  const deleteMutation = useMutation({
    mutationFn: (recipeId: string) => deleteRecipe(recipeId),
    onSuccess: async () => {
      setNotice('配方已删除。')
      await invalidate()
    },
    onError: (error) => setNotice(errorText(error)),
  })

  return (
    <div className="flex flex-col gap-3">
      <NoteText>
        配方 = 栏目顺序 + 字数预算（摘录字符，40..5000）+ 选择规则（已标星 / 最新 / 指定来源）。
        生成器按预算确定性折算条数（约 100 字符/条）——不假装精确排版。
      </NoteText>
      <div className="grid gap-2 sm:grid-cols-2">
        <TextField label="配方名" value={name} onChange={setName} placeholder="例如：晨报配方" />
        <TextField label="栏目 key（短标识）" value={key} onChange={setKey} />
        <TextField label="栏目名" value={label} onChange={setLabel} />
        <TextField label="字数预算（40..5000）" value={budget} onChange={setBudget} />
        <SelectField
          label="选择规则"
          value={rule}
          onChange={setRule}
          options={[
            { value: 'starred', label: '已标星' },
            { value: 'recent', label: '最新 N 条' },
            { value: 'feed', label: '指定来源' },
          ]}
        />
        {rule === 'feed' && <TextField label="来源 URL" value={feedUrl} onChange={setFeedUrl} />}
      </div>
      <button type="button" className={buttonClass} disabled={createMutation.isPending} onClick={() => createMutation.mutate()}>
        保存配方
      </button>
      {notice && <StatusLine tone={createMutation.isError || deleteMutation.isError ? 'error' : 'ok'}>{notice}</StatusLine>}
      {recipes.isError && <StatusLine tone="error">{errorText(recipes.error)}</StatusLine>}
      {recipes.data && recipes.data.count === 0 && <NoteText>还没有配方。</NoteText>}
      {recipes.data?.recipes.map((recipe) => (
        <div
          key={recipe.id}
          data-new281-recipe={recipe.id}
          className="flex flex-wrap items-center justify-between gap-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2 py-1.5"
        >
          <span className="text-sm text-[var(--lumi-text-primary)]">
            {recipe.name}
            <span className="ml-1 text-xs text-[var(--lumi-text-tertiary)]">
              {recipe.sections.map((s) => `${s.label}(${s.rule}/${s.budget})`).join(' → ')}
            </span>
          </span>
          <button
            type="button"
            className={secondaryButtonClass}
            disabled={deleteMutation.isPending}
            onClick={() => deleteMutation.mutate(recipe.id)}
          >
            删除
          </button>
        </div>
      ))}
    </div>
  )
}
