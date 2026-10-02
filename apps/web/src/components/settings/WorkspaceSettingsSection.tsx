/** WorkspaceSettingsSection — 设置 → 工作区（R17 真实设置面）。
 *
 * 取代旧「指路卡」：对当前账户的每个工作区可直接编辑——
 * - 名称 / 说明（PATCH /api/v1/workspaces/{id}；说明缺省 = 不修改）；
 * - 归档 / 恢复（PATCH /workspaces/{id}/archive，F084）；
 * - 导出研究包 Markdown（POST research-pack）；
 * - 删除（DELETE；只解除条目归属，不删来源内容——确认框明示影响）。
 * 全部走既有 workspaces API；后端没有的能力（图标 / 颜色、逐工作区
 * 默认筛选与排序）不做假开关。保留工作区（read-later）由 BFF 拒绝
 * 改名 / 删除，前端对应控件禁用并说明。
 */

import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { AlertCircle, Download, Lock, Pencil, Trash2 } from 'lucide-react'
import {
  ApiError,
  deleteWorkspace,
  exportResearchPackMd,
  patchWorkspaceArchive,
  renameWorkspace,
} from '../../api/client'
import type { Workspace } from '../../api/types'
import { useWorkspaces } from '../../api/queries'
import { Button } from '../ui/Button'
import { FormDialog } from '../ui/FormDialog'
import { Select } from '../ui/Select'
import { SettingsRow } from '../ui/SettingsRow'
import { Skeleton } from '../ui/Skeleton'

const inputClass =
  'min-h-10 w-full rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-3 text-sm text-[var(--lumi-text-primary)] transition-colors duration-[var(--lumi-motion-fast)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)] disabled:opacity-50'

type Feedback = { kind: 'none' } | { kind: 'ok'; message: string } | { kind: 'error'; message: string }

const OK: Feedback = { kind: 'none' }
const okOf = (message: string): Feedback => ({ kind: 'ok', message })
const errorOf = (error: unknown, fallback: string): Feedback => ({
  kind: 'error',
  message: error instanceof ApiError ? error.message : error instanceof Error ? error.message : fallback,
})

export function WorkspaceSettingsSection() {
  const workspaces = useWorkspaces()
  const queryClient = useQueryClient()
  // 用户显式选择；null = 跟随「第一个非保留工作区」的派生默认值。
  const [choice, setChoice] = useState<string | null>(null)
  const [feedback, setFeedback] = useState<Feedback>(OK)

  const items = workspaces.data?.items ?? []
  const selectedId =
    choice !== null && items.some((w) => w.id === choice)
      ? choice
      : (items.find((w) => !w.reserved) ?? items[0])?.id ?? ''

  const selected: Workspace | undefined = items.find((w) => w.id === selectedId)

  function invalidate() {
    return queryClient.invalidateQueries({ queryKey: ['workspaces'] })
  }

  const rename = useMutation({
    mutationFn: (vars: { id: string; name: string; description: string }) =>
      renameWorkspace(vars.id, vars.name, vars.description),
    onSuccess: async (_data, vars) => {
      await invalidate()
      setFeedback(okOf(`已保存「${vars.name}」。`))
    },
    onError: (error) => setFeedback(errorOf(error, '保存失败，请稍后重试。')),
  })
  const archive = useMutation({
    mutationFn: (vars: { id: string; archived: boolean }) =>
      patchWorkspaceArchive(vars.id, vars.archived),
    onSuccess: async (_data, vars) => {
      await invalidate()
      setFeedback(okOf(vars.archived ? '已归档。' : '已恢复。'))
    },
    onError: (error) => setFeedback(errorOf(error, '操作失败，请稍后重试。')),
  })
  const remove = useMutation({
    mutationFn: (id: string) => deleteWorkspace(id),
    onSuccess: async () => {
      setChoice(null)
      await invalidate()
      setFeedback(okOf('工作区已删除；来源内容不受影响。'))
    },
    onError: (error) => setFeedback(errorOf(error, '删除失败，请稍后重试。')),
  })
  const [exportNote, setExportNote] = useState<string | null>(null)
  const [exporting, setExporting] = useState(false)

  function downloadMarkdown(id: string, name: string) {
    setExporting(true)
    setExportNote(null)
    exportResearchPackMd(id)
      .then((text) => {
        const blob = new Blob([text], { type: 'text/markdown' })
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = `workspace-${name}.md`
        a.click()
        URL.revokeObjectURL(url)
        setExportNote('已导出 Markdown 研究包。')
      })
      .catch(() => setExportNote('导出失败，请稍后重试。'))
      .finally(() => setExporting(false))
  }

  if (workspaces.isPending) {
    return (
      <div className="flex flex-col gap-2 py-1" aria-label="正在加载工作区">
        <Skeleton className="h-14 w-full" />
        <Skeleton className="h-14 w-full" />
      </div>
    )
  }
  if (workspaces.isError || workspaces.data === undefined) {
    return (
      <p role="alert" className="flex items-start gap-1.5 text-sm text-[var(--lumi-danger)]">
        <AlertCircle aria-hidden className="mt-0.5 size-4 shrink-0" />
        获取工作区失败：{workspaces.error instanceof Error ? workspaces.error.message : '请稍后重试。'}
      </p>
    )
  }

  if (items.length === 0) {
    return (
      <p className="text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
        还没有工作区。在侧栏「工作区」中创建后，可在这里编辑名称、说明、归档与删除。
      </p>
    )
  }

  const reserved = selected?.reserved === true
  const busy = rename.isPending || archive.isPending || remove.isPending

  return (
    <div className="flex flex-col gap-2 py-1" data-lumi-workspace-settings="">
      <SettingsRow label="选择工作区" help="这里列出当前账户的全部工作区。" controlId="workspace-settings-select">
        <Select
          aria-label="选择工作区"
          value={selectedId}
          disabled={busy}
          onChange={(e) => {
            setChoice(e.target.value)
            setFeedback(OK)
          }}
          options={items.map((w) => ({
            value: w.id,
            label: `${w.name}${w.reserved ? '（保留）' : w.archived ? '（已归档）' : ''} · ${w.itemCount} 条`,
          }))}
        />
      </SettingsRow>

      {selected !== undefined && (
        <>
          <SettingsRow
            label="名称与说明"
            help={reserved ? '保留工作区由系统管理，不可改名。' : selected.description !== '' ? selected.description : '未设置说明。'}
          >
            <WorkspaceEditButton
              workspace={selected}
              disabled={reserved || busy}
              saving={rename.isPending}
              onSave={(name, description) =>
                rename.mutate({ id: selected.id, name, description })
              }
            />
          </SettingsRow>

          <SettingsRow
            label={selected.archived ? '恢复工作区' : '归档工作区'}
            help={
              selected.archived
                ? '恢复后重新出现在侧栏导航。'
                : '归档后默认导航隐藏；深链接仍可打开，不删除任何内容。'
            }
          >
            <Button
              size="sm"
              variant="secondary"
              disabled={busy}
              loading={archive.isPending}
              onClick={() => archive.mutate({ id: selected.id, archived: !selected.archived })}
            >
              {selected.archived ? '恢复' : '归档'}
            </Button>
          </SettingsRow>

          <SettingsRow label="导出内容" help="把工作区条目与笔记导出为 Markdown 研究包。">
            <Button
              size="sm"
              variant="secondary"
              disabled={exporting || busy}
              loading={exporting}
              onClick={() => downloadMarkdown(selected.id, selected.name)}
            >
              <Download aria-hidden className="size-4" />
              导出 Markdown
            </Button>
          </SettingsRow>

          <SettingsRow
            label="删除工作区"
            dangerous
            help={
              reserved
                ? '保留工作区不可删除。'
                : '只解除条目与本工作区的归属；订阅、文章与笔记不受影响。'
            }
          >
            <WorkspaceDeleteButton
              workspace={selected}
              disabled={reserved || busy}
              deleting={remove.isPending}
              onConfirm={() => remove.mutate(selected.id)}
            />
          </SettingsRow>
        </>
      )}

      {feedback.kind !== 'none' && (
        <p
          role={feedback.kind === 'error' ? 'alert' : 'status'}
          aria-live="polite"
          data-lumi-workspace-feedback=""
          className={
            feedback.kind === 'error'
              ? 'text-xs leading-relaxed text-[var(--lumi-danger)]'
              : 'text-xs leading-relaxed text-[var(--lumi-accent-text)]'
          }
        >
          {feedback.message}
        </p>
      )}
      {exportNote !== null && (
        <p role="status" className="text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
          {exportNote}
        </p>
      )}
      <p className="text-[11px] leading-relaxed text-[var(--lumi-text-tertiary)]">
        图标 / 颜色、逐工作区默认筛选与排序暂无服务端字段，提供后会在此出现；
        这里不做假开关。
      </p>
    </div>
  )
}

/** 名称 / 说明编辑（FormDialog；保存走 PATCH，成功后由列表回显）。 */
function WorkspaceEditButton({
  workspace,
  disabled,
  saving,
  onSave,
}: {
  workspace: Workspace
  disabled: boolean
  saving: boolean
  onSave: (name: string, description: string) => void
}) {
  const [open, setOpen] = useState(false)
  const [name, setName] = useState(workspace.name)
  const [description, setDescription] = useState(workspace.description)

  // 每次打开都以服务端当前值打底（外部修改不丢）。
  function openDialog() {
    setName(workspace.name)
    setDescription(workspace.description)
    setOpen(true)
  }

  return (
    <>
      <Button size="sm" variant="secondary" disabled={disabled} onClick={openDialog}>
        <Pencil aria-hidden className="size-3.5" />
        编辑
      </Button>
      <FormDialog
        open={open}
        onClose={() => setOpen(false)}
        title="编辑工作区"
        description="名称必填；说明留空表示清除说明。"
        submitLabel="保存"
        busy={saving}
        onSubmit={() => {
          const trimmed = name.trim()
          // 名称必填；与当前值完全一致时直接关闭（无变更不发起 PATCH）。
          if (trimmed === '' || (trimmed === workspace.name && description === workspace.description)) {
            setOpen(false)
            return
          }
          onSave(trimmed, description)
          setOpen(false)
        }}
      >
        <div>
          <label
            htmlFor="workspace-settings-name"
            className="mb-1.5 block text-sm font-medium text-[var(--lumi-text-primary)]"
          >
            名称
          </label>
          <input
            id="workspace-settings-name"
            type="text"
            value={name}
            maxLength={120}
            disabled={saving}
            onChange={(e) => setName(e.target.value)}
            className={inputClass}
          />
        </div>
        <div>
          <label
            htmlFor="workspace-settings-description"
            className="mb-1.5 block text-sm font-medium text-[var(--lumi-text-primary)]"
          >
            说明
          </label>
          <textarea
            id="workspace-settings-description"
            rows={3}
            maxLength={500}
            value={description}
            disabled={saving}
            placeholder="这个工作区的目标或范围（可选）"
            onChange={(e) => setDescription(e.target.value)}
            className={inputClass}
          />
        </div>
      </FormDialog>
    </>
  )
}

/** 删除确认（FormDialog；说明影响：不删来源内容）。 */
function WorkspaceDeleteButton({
  workspace,
  disabled,
  deleting,
  onConfirm,
}: {
  workspace: Workspace
  disabled: boolean
  deleting: boolean
  onConfirm: () => void
}) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <Button size="sm" variant="danger" disabled={disabled} onClick={() => setOpen(true)}>
        <Trash2 aria-hidden className="size-3.5" />
        删除
      </Button>
      <FormDialog
        open={open}
        onClose={() => setOpen(false)}
        title="删除工作区"
        submitLabel="确认删除"
        busy={deleting}
        onSubmit={() => {
          onConfirm()
          setOpen(false)
        }}
      >
        <div className="flex flex-col gap-2 text-sm leading-relaxed text-[var(--lumi-text-primary)]">
          <p>
            确认删除「{workspace.name}」（{workspace.itemCount} 条）？
          </p>
          <p className="flex items-start gap-1.5 text-xs text-[var(--lumi-text-secondary)]">
            <Lock aria-hidden className="mt-0.5 size-3.5 shrink-0" />
            删除只解除条目与工作区的归属，不删除来源内容：订阅、文章、笔记与阅读状态都保留。
          </p>
        </div>
      </FormDialog>
    </>
  )
}
