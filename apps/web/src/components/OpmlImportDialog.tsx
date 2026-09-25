/** OpmlImportDialog — 0013 Gate 4：订阅页的 OPML 导入入口（移动外壳）。
 *
 * 严格 preview-before-mutation：选择文件后必须先看到真实预览摘要
 * （BFF 无副作用解析），人工点「确认导入」才发生写入；导入后展示
 * server-confirmed 实际结果。流程逻辑全部在 lib/opml-import（与设置
 * 中心内联区块共享），本组件只负责 Dialog 外壳与 a11y。
 * - Escape 关闭（提交中禁用关闭，防误关进行中的 mutation）；
 * - 文件选择 sr-only input + label 关联，44px 触控目标。
 * N018：新增「树对照导入」模式——预览产出对照计划（新建/复用分类、
 * 移动/跳过已订阅 feed），确认后 tree-apply（订阅+建类/移动随行，
 * 写撤销台账）；撤销入口列出最近台账（≤5）并可一键回滚（feed 移回
 * 原分类；空分类无法经 greader API 删除——诚实说明）。
 */

import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Upload } from 'lucide-react'
import {
  OpmlErrorCard,
  OpmlPreviewCard,
  OpmlPreviewItemsCard,
  OpmlResultCard,
} from './OpmlImportFlow'
import { useOpmlImportFlow } from '../lib/opml-import'
import {
  applyOpmlTreeImport,
  listOpmlImportLog,
  previewOpmlTreeImport,
  undoOpmlImport,
} from '../api/client'
import { Button } from './ui/Button'
import { Dialog } from './ui/Dialog'
import { Skeleton } from './ui/Skeleton'
import { cx } from './ui/cx'

// ---- N018 树对照导入流程 -----------------------------------------------------

function TreePlanCard({ plan }: { plan: Awaited<ReturnType<typeof previewOpmlTreeImport>> }) {
  return (
    <div className="flex flex-col gap-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-3 text-xs" data-testid="opml-tree-plan">
      <p className="text-sm font-medium text-[var(--lumi-text-primary)]">树对照计划</p>
      <ul className="list-disc pl-4 leading-relaxed text-[var(--lumi-text-secondary)]">
        <li>文件 feed 数：{plan.totalFeeds}（不可用 {plan.invalidEntries}）</li>
        <li data-testid="tree-create-categories">
          新建分类：{plan.createCategories.length > 0 ? plan.createCategories.join('、') : '无'}
        </li>
        <li>复用分类：{plan.reuseCategories.length > 0 ? plan.reuseCategories.join('、') : '无'}</li>
        <li data-testid="tree-new-feeds">将订阅：{plan.newFeeds.length} 个</li>
        <li data-testid="tree-move-feeds">
          将移动：{plan.moveFeeds.length} 个（已订阅但分类不同）
        </li>
        <li>
          已订阅保持不动：{plan.duplicateFeeds.filter((d) => d.action === 'skip').length} 个
        </li>
      </ul>
      {plan.notes.length > 0 && (
        <ul className="list-disc pl-4 leading-relaxed text-[11px] text-[var(--lumi-text-tertiary)]">
          {plan.notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      )}
    </div>
  )
}

function TreeImportSection() {
  const queryClient = useQueryClient()
  const [file, setFile] = useState<File | null>(null)
  const [plan, setPlan] = useState<Awaited<ReturnType<typeof previewOpmlTreeImport>> | null>(null)
  const [result, setResult] = useState<Awaited<ReturnType<typeof applyOpmlTreeImport>> | null>(null)
  const [localError, setLocalError] = useState<string | null>(null)
  const logQuery = useQuery({
    queryKey: ['opml-import-log'],
    queryFn: () => listOpmlImportLog(),
  })
  const previewMutation = useMutation({
    mutationFn: (selected: File) => previewOpmlTreeImport(selected),
    onSuccess: (data) => setPlan(data),
  })
  const applyMutation = useMutation({
    mutationFn: () => applyOpmlTreeImport(file as File),
    onSuccess: async (data) => {
      setResult(data)
      await queryClient.invalidateQueries({ queryKey: ['opml-import-log'] })
      await queryClient.invalidateQueries({ queryKey: ['subscriptions'] })
    },
  })
  const undoMutation = useMutation({
    mutationFn: (logId: number) => undoOpmlImport(logId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['opml-import-log'] })
      await queryClient.invalidateQueries({ queryKey: ['subscriptions'] })
    },
  })

  function selectFile(selected: File) {
    setLocalError(null)
    setPlan(null)
    setResult(null)
    if (selected.size > 2 * 1024 * 1024) {
      setFile(null)
      setLocalError('OPML 文件超过 2 MiB 上限。')
      return
    }
    setFile(selected)
    previewMutation.mutate(selected)
  }

  const busy = previewMutation.isPending || applyMutation.isPending || undoMutation.isPending
  const logs = logQuery.data?.items ?? []

  return (
    <div className="flex flex-col gap-3">
      {!result && (
        <label htmlFor="opml-tree-import-file">
          <span
            className={
              file === null
                ? 'flex min-h-11 items-center gap-2 text-sm font-medium text-[var(--lumi-text-primary)]'
                : 'sr-only'
            }
          >
            <Upload aria-hidden className="size-4" />
            选择 OPML 文件（树对照）
          </span>
          <input
            id="opml-tree-import-file"
            type="file"
            accept=".opml,.xml,application/xml,text/xml,text/x-opml"
            disabled={busy}
            className="sr-only"
            onChange={(e) => {
              const f = e.target.files?.[0]
              if (f) selectFile(f)
              e.target.value = ''
            }}
          />
        </label>
      )}
      {file !== null && !result && (
        <p className="truncate text-xs text-[var(--lumi-text-tertiary)]" title={file.name}>
          文件：{file.name}
        </p>
      )}
      {localError !== null && (
        <p role="alert" className="text-xs text-[var(--lumi-danger)]">{localError}</p>
      )}
      {previewMutation.isPending && (
        <div className="flex flex-col gap-2" aria-label="正在解析 OPML">
          <Skeleton className="h-5 w-2/3" />
          <Skeleton className="h-4 w-1/2" />
        </div>
      )}
      {previewMutation.isError && (
        <OpmlErrorCard
          title="解析失败"
          detail={previewMutation.error instanceof Error ? previewMutation.error.message : null}
        />
      )}
      {!result && plan !== null && <TreePlanCard plan={plan} />}
      {applyMutation.isPending && (
        <p role="status" className="text-sm text-[var(--lumi-text-secondary)]">正在应用计划，请勿关闭窗口…</p>
      )}
      {applyMutation.isError && (
        <p role="alert" className="text-xs text-[var(--lumi-danger)]">
          {applyMutation.error instanceof Error ? applyMutation.error.message : '请稍后重试'}
        </p>
      )}
      {result !== null && (
        <div className="flex flex-col gap-1.5 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-3 text-xs" data-testid="opml-tree-result">
          <p className="text-sm font-medium text-[var(--lumi-text-primary)]">
            应用完成（撤销台账 #{result.logId}）
          </p>
          <p className="text-[var(--lumi-text-secondary)]">
            新订阅 {result.added.length} · 移动 {result.moved.length} ·
            跳过 {result.skipped.length} · 失败 {result.failed.length}
          </p>
          {result.categoriesCreated.length > 0 && (
            <p className="text-[var(--lumi-text-tertiary)]">
              新建分类：{result.categoriesCreated.join('、')}
            </p>
          )}
        </div>
      )}

      {/* 撤销台账（≤5 行；每行至多撤销一次） */}
      <div className="flex flex-col gap-1.5">
        <p className="text-xs font-medium text-[var(--lumi-text-primary)]">撤销台账</p>
        {logs.length === 0 && (
          <p className="text-xs text-[var(--lumi-text-tertiary)]">还没有可撤销的树对照导入。</p>
        )}
        {logs.map((log) => (
          <div
            key={log.id}
            className="flex items-center gap-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2.5 py-1.5 text-xs"
          >
            <span className="min-w-0 flex-1 text-[var(--lumi-text-secondary)]">
              #{log.id} · 新建 {log.createdCategoryLabels.length} 分类 · 移动{' '}
              {log.movedFeeds.length} 个来源
              {log.undoneAt !== null && '（已撤销）'}
            </span>
            {log.undoneAt === null && (
              <Button
                size="sm"
                variant="ghost"
                disabled={busy}
                onClick={() => undoMutation.mutate(log.id)}
              >
                撤销
              </Button>
            )}
          </div>
        ))}
        {undoMutation.isError && (
          <p role="alert" className="text-xs text-[var(--lumi-danger)]">
            {undoMutation.error instanceof Error ? undoMutation.error.message : '撤销失败'}
          </p>
        )}
        {undoMutation.isSuccess && (
          <p role="status" className="text-xs text-[var(--lumi-text-secondary)]">
            已撤销：移回 {undoMutation.data.movedBack.length} 个来源；
            {undoMutation.data.categoriesNotDeleted.length > 0 &&
              ` 新建分类 ${undoMutation.data.categoriesNotDeleted.length} 个无法经 greader API 删除（空分类可在 FreshRSS 原生界面清理）。`}
          </p>
        )}
      </div>
    </div>
  )
}

// ---- 对话框外壳（flat / tree 两种模式共用） -----------------------------------

export default function OpmlImportDialog({
  open,
  onClose,
}: {
  open: boolean
  onClose: () => void
}) {
  const flow = useOpmlImportFlow()
  const [mode, setMode] = useState<'flat' | 'tree'>('flat')

  // 打开时重置全部本地状态（上一次会话不留残留）
  useEffect(() => {
    if (open) {
      flow.reset()
      setMode('flat')
    }
    // reset 是流程 hook 的稳定方法；依赖只看 open
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  function close() {
    if (mode === 'flat' ? flow.busy : false) return // 提交中不允许误关
    onClose()
  }

  const canConfirm =
    flow.file !== null && flow.preview !== null && flow.selectedCount > 0 && !flow.busy

  return (
    <Dialog
      open={open}
      onClose={close}
      title="导入 OPML"
      fullscreenOnMobile
      panelClassName="max-w-lg"
      footer={
        mode === 'tree' ? (
          <Button variant="primary" onClick={onClose}>
            关闭
          </Button>
        ) : flow.result !== null ? (
          <Button variant="primary" onClick={onClose}>
            完成
          </Button>
        ) : (
          <>
            <Button variant="ghost" onClick={close} disabled={flow.busy}>
              取消
            </Button>
            <Button variant="primary" onClick={flow.confirmImport} disabled={!canConfirm}>
              {flow.importPending ? '导入中…' : '确认导入'}
            </Button>
          </>
        )
      }
    >
      <div className="flex flex-col gap-4">
        {/* N018：模式切换（逐项导入 = 既有合并语义；树对照 = 分类对照计划）。 */}
        <div role="tablist" aria-label="导入模式" className="flex gap-1.5">
          {(
            [
              ['flat', '逐项导入'],
              ['tree', '树对照导入'],
            ] as const
          ).map(([value, label]) => (
            <button
              key={value}
              type="button"
              role="tab"
              aria-selected={mode === value}
              onClick={() => setMode(value)}
              className={cx(
                'min-h-9 rounded-[var(--lumi-radius-md)] px-3 text-xs',
                mode === value
                  ? 'bg-[var(--lumi-accent-soft)] text-[var(--lumi-accent)]'
                  : 'text-[var(--lumi-text-secondary)] hover:bg-[var(--lumi-surface-hover)]',
              )}
            >
              {label}
            </button>
          ))}
        </div>

        {mode === 'tree' ? (
          <TreeImportSection />
        ) : (
          <>
            {!flow.result && (
              <label
                htmlFor="opml-import-file"
                className={flow.file !== null ? 'sr-only' : undefined}
              >
                <span
                  className={flow.file === null ? 'flex min-h-11 items-center gap-2 text-sm font-medium text-[var(--lumi-text-primary)]' : 'sr-only'}
                >
                  <Upload aria-hidden className="size-4" />
                  选择 OPML 文件
                </span>
                <input
                  id="opml-import-file"
                  ref={(node) => {
                    if (node) node.tabIndex = 0
                  }}
                  type="file"
                  accept=".opml,.xml,application/xml,text/xml,text/x-opml"
                  disabled={flow.busy}
                  className="sr-only"
                  onChange={(e) => {
                    const f = e.target.files?.[0]
                    if (f) flow.selectFile(f)
                    e.target.value = ''
                  }}
                />
                {flow.file === null && !flow.busy && (
                  <span className="mt-1 block text-xs text-[var(--lumi-text-secondary)]">
                    将先解析预览，确认后才会写入 FreshRSS（合并导入，不删除现有订阅）。
                  </span>
                )}
              </label>
            )}

            {flow.file !== null && !flow.result && (
              <p className="truncate text-xs text-[var(--lumi-text-tertiary)]" title={flow.file.name}>
                文件：{flow.file.name}
              </p>
            )}

            {flow.previewPending && (
              <div className="flex flex-col gap-2" aria-label="正在解析 OPML">
                <Skeleton className="h-5 w-2/3" />
                <Skeleton className="h-4 w-1/2" />
              </div>
            )}

            {flow.errorVisible && flow.error !== null && (
              <OpmlErrorCard title={flow.error.title} detail={flow.error.detail} />
            )}

            {!flow.result && flow.preview !== null && <OpmlPreviewCard preview={flow.preview} />}

            {/* F002：逐项勾选（预览后可全选/反选/单项切换） */}
            {!flow.result && flow.preview !== null && (
              <OpmlPreviewItemsCard
                preview={flow.preview}
                selected={flow.selected}
                onToggleItem={flow.toggleItem}
                onToggleAll={flow.toggleAll}
                onInvert={flow.invertSelection}
              />
            )}

            {flow.importPending && (
              <p role="status" className="text-sm text-[var(--lumi-text-secondary)]">
                正在导入，请勿关闭窗口…
              </p>
            )}

            {flow.result !== null && <OpmlResultCard result={flow.result} />}
          </>
        )}
      </div>
    </Dialog>
  )
}
