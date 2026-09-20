/** QaTemplateBar — F030 问答模板（ArticleConversation 输入区上方）。
 *
 * 模板下拉（选择即填入输入框，可再编辑）+「存为模板」（当前输入→命名）
 * + 管理（重命名/删除）。模板是普通文本：React 转义渲染即可，服务端
 * 不做 HTML 组装；模板与具体文章无关（切换文章列表不变）。
 */

import { useState } from 'react'
import { BookmarkPlus, Pencil, Trash2 } from 'lucide-react'
import type { QaTemplateView } from '../api/client'
import { useQaTemplateMutations, useQaTemplates } from '../api/queries'
import { Button } from './ui/Button'

export default function QaTemplateBar({
  onPick,
  draft,
}: {
  onPick: (text: string) => void
  draft: string
}) {
  const templates = useQaTemplates()
  const { create, patch, remove } = useQaTemplateMutations()
  const [managing, setManaging] = useState(false)
  const [saving, setSaving] = useState(false)
  const [name, setName] = useState('')
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editName, setEditName] = useState('')
  const [error, setError] = useState<string | null>(null)

  const items = templates.data?.items ?? []

  function saveCurrent() {
    const text = draft.trim()
    if (!text) {
      setError('当前输入为空，无法存为模板。')
      return
    }
    if (!name.trim()) {
      setError('请给模板起个名字。')
      return
    }
    create.mutate(
      { name: name.trim(), text },
      {
        onSuccess: () => {
          setSaving(false)
          setName('')
          setError(null)
        },
        onError: () => setError('保存失败（文本 ≤500 字）。'),
      },
    )
  }

  function rename(template: QaTemplateView) {
    if (!editName.trim()) return
    patch.mutate(
      { id: template.id, body: { name: editName.trim() } },
      { onSuccess: () => setEditingId(null) },
    )
  }

  return (
    <div className="mb-2 flex flex-wrap items-center gap-1.5 text-xs" data-lumi-qa-templates="">
      <select
        aria-label="问答模板"
        value=""
        onChange={(e) => {
          const template = items.find((item) => item.id === e.target.value)
          if (template) onPick(template.text)
        }}
        className="min-h-8 max-w-56 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-1.5"
      >
        <option value="">选择模板…</option>
        {items.map((template) => (
          <option key={template.id} value={template.id}>
            {template.name}
          </option>
        ))}
      </select>
      <Button size="sm" variant="ghost" onClick={() => setSaving((v) => !v)} aria-pressed={saving}>
        <BookmarkPlus aria-hidden className="size-3.5" />
        存为模板
      </Button>
      <Button size="sm" variant="ghost" aria-pressed={managing} onClick={() => setManaging((v) => !v)}>
        管理
      </Button>
      {saving ? (
        <span className="flex items-center gap-1">
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="模板名称"
            aria-label="模板名称"
            maxLength={60}
            className="min-h-8 w-32 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-1.5"
          />
          <Button size="sm" variant="secondary" onClick={saveCurrent} disabled={create.isPending}>
            保存
          </Button>
        </span>
      ) : null}
      {managing ? (
        <ul className="mt-1 flex w-full flex-col gap-1">
          {items.map((template) => (
            <li key={template.id} className="flex items-center gap-1.5 rounded-[var(--lumi-radius-md)] bg-[var(--lumi-surface)] px-2 py-1">
              {editingId === template.id ? (
                <>
                  <input
                    value={editName}
                    onChange={(e) => setEditName(e.target.value)}
                    aria-label={`重命名模板 ${template.name}`}
                    className="min-h-7 flex-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-1.5"
                  />
                  <Button size="sm" variant="secondary" onClick={() => rename(template)}>
                    确定
                  </Button>
                </>
              ) : (
                <>
                  <span className="min-w-0 flex-1 truncate">{template.name}</span>
                  <Button
                    size="sm"
                    variant="ghost"
                    aria-label={`重命名 ${template.name}`}
                    onClick={() => {
                      setEditingId(template.id)
                      setEditName(template.name)
                    }}
                  >
                    <Pencil aria-hidden className="size-3.5" />
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    aria-label={`删除模板 ${template.name}`}
                    onClick={() => remove.mutate(template.id)}
                  >
                    <Trash2 aria-hidden className="size-3.5" />
                  </Button>
                </>
              )}
            </li>
          ))}
          {items.length === 0 ? (
            <li className="text-[var(--lumi-text-tertiary)]">还没有模板。</li>
          ) : null}
        </ul>
      ) : null}
      {error ? (
        <p role="alert" className="w-full text-[var(--lumi-danger)]">
          {error}
        </p>
      ) : null}
    </div>
  )
}
