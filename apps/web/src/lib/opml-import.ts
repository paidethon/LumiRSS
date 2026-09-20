/** opml-import — 0013 Gate 4：OPML 导入流程逻辑（hook + 纯函数）。
 *
 * 严格 preview-before-mutation：选择文件只发无副作用的 preview 请求，
 * 人工确认后才发 import（merge-only，不删除、不覆盖现有订阅）。
 * 文件大小前端第一道拦截（> 2 MiB 不发请求），BFF 同规则兜底。
 * mutation 后只 invalidate（invalidateSubscriptionState），不做
 * optimistic updates；结果全部来自 server-confirmed 响应。 */

import { useState } from 'react'
import { exportOpml } from '../api/client'
import { useOpmlImportMutation, useOpmlPreviewMutation } from '../api/queries'
import type { OpmlImportPreview, OpmlImportResult } from '../api/types'
import { managementErrorText } from './management-errors'
/** 与 BFF MAX_OPML_BYTES 一致（前端第一道，非安全边界）。 */
export const OPML_MAX_BYTES = 2 * 1024 * 1024

/** import result 的失败码 → 诚实文案（BFF 只回稳定 code，不透传上游文本）。 */
export function opmlFailureLabel(error: string): string {
  switch (error) {
    case 'feed_rejected':
      return 'FreshRSS 无法添加该源（地址无效或不可达）'
    case 'connection_error':
      return '连接 FreshRSS 失败'
    case 'authentication_error':
      return 'FreshRSS 凭据被拒绝'
    default:
      return 'FreshRSS 返回异常'
  }
}

/** 导入流程状态机：file → preview → confirm → result。 */
export function useOpmlImportFlow() {
  const [file, setFile] = useState<File | null>(null)
  const [localError, setLocalError] = useState<string | null>(null)
  const [result, setResult] = useState<OpmlImportResult | null>(null)
  // F002：逐项勾选（index 集合；预览到达时按 status 计算默认勾选）
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const previewMutation = useOpmlPreviewMutation()
  const importMutation = useOpmlImportMutation()

  const busy =
    previewMutation.isPending || importMutation.isPending || result !== null

  function reset() {
    setFile(null)
    setLocalError(null)
    setResult(null)
    setSelected(new Set())
    previewMutation.reset()
    importMutation.reset()
  }

  function selectFile(selectedFile: File) {
    setLocalError(null)
    setResult(null)
    setSelected(new Set())
    if (selectedFile.size > OPML_MAX_BYTES) {
      // 本地拦截：不发请求（BFF 侧同规则兜底）
      setFile(null)
      previewMutation.reset()
      setLocalError('OPML 文件超过 2 MiB 上限。')
      return
    }
    setFile(selectedFile)
    previewMutation.mutate(selectedFile, {
      onSuccess: (previewData) => {
        // F002：默认勾选 new + category_conflict；duplicate/invalid 默认不选
        const defaults = new Set<number>()
        for (const item of previewData.items ?? []) {
          if (item.status === 'new' || item.status === 'category_conflict') {
            defaults.add(item.index)
          }
        }
        setSelected(defaults)
      },
    })
  }

  /** F002：切换单项勾选。 */
  function toggleItem(index: number) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(index)) next.delete(index)
      else next.add(index)
      return next
    })
  }

  /** F002：全选 / 全不选（以 items 全集为界）。 */
  function toggleAll() {
    const items = preview?.items ?? []
    const allSelected = items.length > 0 && items.every((i) => selected.has(i.index))
    setSelected(allSelected ? new Set() : new Set(items.map((i) => i.index)))
  }

  /** F002：反选。 */
  function invertSelection() {
    const items = preview?.items ?? []
    setSelected(new Set(items.filter((i) => !selected.has(i.index)).map((i) => i.index)))
  }

  function confirmImport() {
    if (file === null || busy || selected.size === 0) return
    importMutation.mutate(
      { file, selectedIndexes: [...selected] },
      { onSuccess: (r) => setResult(r) },
    )
  }

  const preview: OpmlImportPreview | null = previewMutation.data ?? null
  const error =
    localError !== null
      ? { title: localError, detail: null }
      : previewMutation.isError || importMutation.isError
        ? managementErrorText(previewMutation.error ?? importMutation.error)
        : null

  return {
    file,
    preview,
    result,
    busy,
    error,
    errorVisible:
      error !== null && !previewMutation.isPending && !importMutation.isPending,
    previewPending: previewMutation.isPending,
    importPending: importMutation.isPending,
    selected,
    selectedCount: selected.size,
    toggleItem,
    toggleAll,
    invertSelection,
    selectFile,
    confirmImport,
    reset,
  }
}

/** OPML 导出流程 hook（0014a Gate 1：设置「订阅与来源」与订阅管理页
 * 共用同一导出状态机；复用 BFF 代理下载，浏览器不接触 FreshRSS）。
 * F003：exportOnce 可携带 selection（仅导出所选订阅/分类）。 */
export function useOpmlExportFlow() {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState(false)

  async function exportOnce(selection?: {
    subscriptionRefs?: string[]
    categoryIds?: string[]
  }) {
    setError(null)
    setDone(false)
    setBusy(true)
    try {
      await exportOpml(selection)
      setDone(true)
    } catch (e) {
      setError(managementErrorText(e).title)
    } finally {
      setBusy(false)
    }
  }

  return { busy, error, done, exportOnce }
}
