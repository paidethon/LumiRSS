/** WorkspaceExtras — F083 模板 / F084 归档入口 / F088 资料包 ZIP 导出
 * + N117 模板结构承载 + N119 归档摘要卡。
 *
 * - SaveAsTemplateDialog：仅保存工作区配置（非条目、非凭据）为模板；
 *   N117 includeStructure 可额外快照结构（组序/分节/看板列/收集规则
 *   条件，绝不包含条目内容）；
 * - TemplatesDialog：从模板创建（示例条目以 ref 引用，失效诚实跳过）
 *   + 模板管理（列表 / 删除）+ N117 结构恢复（空壳：分节/组序/收集
 *   规则条件，内容绝不复制）；
 * - ArchivedBar：归档工作区列表（默认导航隐藏，此处显式可见）+ 恢复
 *   + N119 摘要卡（itemCount/doneCount/目标进度/存续天数）；
 * - ResearchPackExportDialog：预览（estBytes / missing / 快照清单）→
 *   勾选快照 → ZIP 下载（manifest 含 sha256；>20MB 服务端 413 诚实报错）。
 */

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArchiveRestore, Trash2 } from 'lucide-react'
import {
  createWorkspaceFromTemplate,
  deleteWorkspaceTemplate,
  exportResearchPackZip,
  listArchivedWorkspaces,
  listWorkspaceTemplates,
  patchWorkspaceArchive,
  previewResearchPackW5,
  saveWorkspaceAsTemplate,
} from '../api/client'
import { Button } from './ui/Button'
import { Dialog } from './ui/Dialog'
import { cx } from './ui/cx'

// ---- F083 保存为模板 ---------------------------------------------------------

export function SaveAsTemplateDialog({
  workspaceId,
  onClose,
}: {
  workspaceId: string
  onClose: () => void
}) {
  const [name, setName] = useState('')
  // N117：是否额外快照工作区结构（组序/分节/看板列/收集规则条件）。
  const [includeStructure, setIncludeStructure] = useState(false)
  const queryClient = useQueryClient()
  const save = useMutation({
    mutationFn: () => saveWorkspaceAsTemplate(workspaceId, name.trim(), includeStructure),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['workspace-templates'] })
      onClose()
    },
  })
  return (
    <Dialog
      open
      onClose={onClose}
      title="保存为模板"
      footer={
        <div className="flex w-full justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={onClose}>取消</Button>
          <Button
            variant="primary"
            size="sm"
            disabled={name.trim() === '' || save.isPending}
            onClick={() => save.mutate()}
          >
            {save.isPending ? '保存中…' : '保存模板'}
          </Button>
        </div>
      }
    >
      <div className="flex flex-col gap-2" data-save-template="">
        <p className="text-xs text-[var(--lumi-text-secondary)]">
          只保存工作区配置（名称 / 描述等）；条目与来源凭据不会进入模板。
        </p>
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="模板名（≤50 字）"
          aria-label="模板名"
          className="rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-3 py-2 text-sm text-[var(--lumi-text-primary)]"
        />
        <label className="flex items-start gap-2 text-xs text-[var(--lumi-text-secondary)]">
          <input
            type="checkbox"
            checked={includeStructure}
            onChange={(e) => setIncludeStructure(e.target.checked)}
            aria-label="包含工作区结构"
            data-template-structure=""
            className="mt-0.5"
          />
          <span>
            包含工作区结构（N117）
            <span className="block text-[11px] text-[var(--lumi-text-tertiary)]">
              携带分组顺序、分节大纲、看板状态列与收集规则条件（空壳——
              绝不包含任何条目内容）。
            </span>
          </span>
        </label>
        {save.isError && (
          <p role="alert" className="text-xs text-[var(--lumi-danger)]">
            {save.error instanceof Error ? save.error.message : '保存失败，请稍后重试。'}
          </p>
        )}
      </div>
    </Dialog>
  )
}

// ---- F083 模板管理 / 从模板创建 ------------------------------------------------

export function TemplatesDialog({
  onClose,
  onCreated,
}: {
  onClose: () => void
  onCreated?: (workspaceId: string) => void
}) {
  const templates = useQuery({
    queryKey: ['workspace-templates'],
    queryFn: () => listWorkspaceTemplates(),
  })
  const [selected, setSelected] = useState('')
  const [name, setName] = useState('')
  const [includeExamples, setIncludeExamples] = useState(false)
  // N117：模板带 structure 快照时可恢复空壳结构（分节/组序/收集规则）。
  const [includeStructure, setIncludeStructure] = useState(false)
  const [created, setCreated] = useState<{ id: string; skipped: string[] } | null>(null)
  const queryClient = useQueryClient()
  const create = useMutation({
    mutationFn: () =>
      createWorkspaceFromTemplate({
        templateId: selected,
        name: name.trim(),
        includeExampleItems: includeExamples,
        exampleRefs: [],
        includeStructure,
      }),
    onSuccess: async (result) => {
      await queryClient.invalidateQueries({ queryKey: ['workspaces'] })
      setCreated({ id: result.workspace.id, skipped: result.skippedExampleRefs })
      onCreated?.(result.workspace.id)
    },
  })
  const del = useMutation({
    mutationFn: (id: string) => deleteWorkspaceTemplate(id),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['workspace-templates'] })
    },
  })
  const items = templates.data?.items ?? []

  return (
    <Dialog open onClose={onClose} title="工作区模板" panelClassName="max-w-lg">
      <div className="flex flex-col gap-3" data-templates-dialog="">
        {templates.isPending && <p className="text-xs text-[var(--lumi-text-tertiary)]">加载中…</p>}
        {templates.isError && (
          <p role="alert" className="text-xs text-[var(--lumi-danger)]">模板加载失败。</p>
        )}
        {!templates.isPending && items.length === 0 && (
          <p className="text-xs text-[var(--lumi-text-tertiary)]">
            还没有模板。在某个工作区的菜单里选「保存为模板」。
          </p>
        )}
        <ul className="flex flex-col gap-1.5">
          {items.map((t) => (
            <li
              key={t.id}
              data-template-id={t.id}
              className={cx(
                'flex items-center gap-2 rounded-[var(--lumi-radius-md)] border px-2.5 py-1.5 text-xs',
                selected === t.id
                  ? 'border-[var(--lumi-accent)] bg-[var(--lumi-accent-soft)]'
                  : 'border-[var(--lumi-border)]',
              )}
            >
              <label className="min-w-0 flex-1 cursor-pointer">
                <input
                  type="radio"
                  name="workspace-template"
                  checked={selected === t.id}
                  onChange={() => setSelected(t.id)}
                  aria-label={`选择模板：${t.name}`}
                  className="mr-2"
                />
                <span className="text-[var(--lumi-text-primary)]">{t.name}</span>
              </label>
              <IconButton2 label={`删除模板 ${t.name}`} onClick={() => del.mutate(t.id)} disabled={del.isPending} />
            </li>
          ))}
        </ul>

        {selected !== '' && created === null && (
          <div className="flex flex-col gap-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] p-2.5">
            <label className="flex flex-col gap-1 text-xs">
              <span className="text-[var(--lumi-text-secondary)]">新工作区名</span>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                aria-label="新工作区名"
                className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-sm text-[var(--lumi-text-primary)]"
              />
            </label>
            <label className="flex items-center gap-2 text-xs text-[var(--lumi-text-secondary)]">
              <input
                type="checkbox"
                checked={includeExamples}
                onChange={(e) => setIncludeExamples(e.target.checked)}
              />
              加入示例条目（以引用加入，不复制内容；失效 ref 诚实跳过）
            </label>
            <label className="flex items-start gap-2 text-xs text-[var(--lumi-text-secondary)]">
              <input
                type="checkbox"
                checked={includeStructure}
                onChange={(e) => setIncludeStructure(e.target.checked)}
                data-template-apply-structure=""
              />
              <span>
                恢复模板结构（N117，空壳）
                <span className="block text-[11px] text-[var(--lumi-text-tertiary)]">
                  模板携带结构快照时可用：新建空分节、恢复分组顺序与收集
                  规则条件；条目内容绝不复制。
                </span>
              </span>
            </label>
            <div>
              <Button
                variant="primary"
                size="sm"
                disabled={name.trim() === '' || create.isPending}
                onClick={() => create.mutate()}
              >
                {create.isPending ? '创建中…' : '从模板创建'}
              </Button>
            </div>
          </div>
        )}
        {created !== null && (
          <p role="status" className="text-xs text-[var(--lumi-text-primary)]" data-created-workspace={created.id}>
            已创建工作区。{created.skipped.length > 0 ? `跳过失效示例 ref：${created.skipped.join('、')}` : ''}
          </p>
        )}
        {create.isError && (
          <p role="alert" className="text-xs text-[var(--lumi-danger)]">
            {create.error instanceof Error ? create.error.message : '创建失败，请稍后重试。'}
          </p>
        )}
        {del.isError && (
          <p role="alert" className="text-xs text-[var(--lumi-danger)]">模板删除失败。</p>
        )}
      </div>
    </Dialog>
  )
}

function IconButton2({ label, onClick, disabled }: { label: string; onClick: () => void; disabled?: boolean }) {
  return (
    <button
      type="button"
      aria-label={label}
      disabled={disabled}
      onClick={onClick}
      className="rounded-[var(--lumi-radius-md)] p-1 text-[var(--lumi-text-tertiary)] transition-colors hover:bg-[var(--lumi-surface-hover)] hover:text-[var(--lumi-danger)]"
    >
      <Trash2 aria-hidden className="size-3.5" />
    </button>
  )
}

// ---- F084 归档列表 -----------------------------------------------------------

/** F084 归档列表 + N119 摘要卡（itemCount / doneCount / 目标进度 /
 * 存续天数——全部真实行派生，绝不估算）。 */
export function ArchivedBar() {
  const archived = useQuery({
    queryKey: ['workspace-archive'],
    queryFn: () => listArchivedWorkspaces(),
  })
  const queryClient = useQueryClient()
  const restore = useMutation({
    mutationFn: (id: string) => patchWorkspaceArchive(id, false),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['workspaces'] })
      await queryClient.invalidateQueries({ queryKey: ['workspace-archive'] })
    },
  })
  const items = archived.data ?? []
  if (archived.isPending || items.length === 0) return null
  return (
    <div
      data-archived-bar=""
      className="mt-2 flex flex-wrap items-stretch gap-1.5 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] px-2.5 py-1.5 text-xs"
    >
      <span className="self-center text-[var(--lumi-text-tertiary)]">已归档：</span>
      {items.map((w) => (
        <span
          key={w.id}
          data-archived-card={w.id}
          className="flex flex-col gap-0.5 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2 py-1 text-[var(--lumi-text-secondary)]"
        >
          <span className="flex items-center gap-1 font-medium text-[var(--lumi-text-primary)]">
            {w.name}
            <button
              type="button"
              aria-label={`恢复工作区 ${w.name}`}
              disabled={restore.isPending}
              onClick={() => restore.mutate(w.id)}
              className="rounded p-0.5 hover:bg-[var(--lumi-surface-hover)]"
            >
              <ArchiveRestore aria-hidden className="size-3" />
            </button>
          </span>
          <span className="flex flex-wrap gap-x-2 text-[11px]" data-archived-summary="">
            <span>{w.summary.itemCount} 条</span>
            <span>完成 {w.summary.doneCount}</span>
            {w.summary.goalProgress !== null && (
              <span>
                目标 {w.summary.goalProgress.doneCount}/{w.summary.goalProgress.targetCount}
              </span>
            )}
            <span>存续 {w.summary.daysActive} 天</span>
          </span>
        </span>
      ))}
      {restore.isError && (
        <span role="alert" className="text-[var(--lumi-danger)]">
          恢复失败：{restore.error instanceof Error ? restore.error.message : '请稍后重试。'}
        </span>
      )}
    </div>
  )
}

// ---- F088 资料包 ZIP 导出 ------------------------------------------------------

export function ResearchPackExportDialog({
  workspaceId,
  onClose,
}: {
  workspaceId: string
  onClose: () => void
}) {
  const [selectedSnapshots, setSelectedSnapshots] = useState<Set<string>>(new Set())
  const preview = useMutation({
    mutationFn: () => previewResearchPackW5(workspaceId, [...selectedSnapshots]),
  })
  const download = useMutation({
    mutationFn: () => exportResearchPackZip(workspaceId, [...selectedSnapshots]),
    onSuccess: () => {
      onClose()
    },
  })
  const snapshots = preview.data?.snapshots ?? []

  return (
    <Dialog
      open
      onClose={onClose}
      title="导出研究包（ZIP）"
      panelClassName="max-w-lg"
      footer={
        <div className="flex w-full justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={onClose}>取消</Button>
          {preview.data !== undefined && (
            <Button
              variant="primary"
              size="sm"
              disabled={download.isPending}
              onClick={() => download.mutate()}
            >
              {download.isPending ? '打包中…' : '下载 ZIP'}
            </Button>
          )}
        </div>
      }
    >
      <div className="flex flex-col gap-3" data-research-export="">
        {preview.data === undefined && (
          <>
            <Button variant="secondary" size="sm" disabled={preview.isPending} onClick={() => preview.mutate()}>
              {preview.isPending ? '生成预览…' : '生成预览'}
            </Button>
            {preview.isError && (
              <p role="alert" className="text-xs text-[var(--lumi-danger)]">
                预览失败：{preview.error instanceof Error ? preview.error.message : '请稍后重试。'}
              </p>
            )}
          </>
        )}
        {preview.data !== undefined && (
          <>
            <p role="status" className="text-xs text-[var(--lumi-text-primary)]">
              条目 {preview.data.entryCount} 条 · 预估 {(preview.data.estBytes / 1024).toFixed(0)} KB
              {preview.data.missingCount > 0 ? ` · 缺失资产 ${preview.data.missingCount} 项（将记入 manifest）` : ''}
              ，manifest 含逐文件 sha256。
            </p>
            {snapshots.length > 0 && (
              <fieldset className="flex flex-col gap-1 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] p-2.5 text-xs">
                <legend className="px-1 text-[var(--lumi-text-secondary)]">纳入快照（可选）</legend>
                {snapshots.map((s) => (
                  <label key={s.uuid} className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={selectedSnapshots.has(s.uuid)}
                      onChange={() =>
                        setSelectedSnapshots((prev) => {
                          const next = new Set(prev)
                          if (next.has(s.uuid)) next.delete(s.uuid)
                          else next.add(s.uuid)
                          return next
                        })
                      }
                      aria-label={`纳入快照：${s.title}`}
                    />
                    <span className="min-w-0 flex-1 truncate text-[var(--lumi-text-primary)]">{s.title}</span>
                    <span className="text-[var(--lumi-text-tertiary)]">{(s.bytes / 1024).toFixed(0)} KB</span>
                  </label>
                ))}
              </fieldset>
            )}
          </>
        )}
        {download.isError && (
          <p role="alert" className="text-xs text-[var(--lumi-danger)]">
            导出失败：{download.error instanceof Error ? download.error.message : '请稍后重试。'}
          </p>
        )}
      </div>
    </Dialog>
  )
}
