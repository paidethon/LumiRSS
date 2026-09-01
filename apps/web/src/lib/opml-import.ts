/** opml-import — 0013 Gate 4：OPML 导入流程逻辑（hook + 纯函数）。
 *
 * 严格 preview-before-mutation：选择文件只发无副作用的 preview 请求，
 * 人工确认后才发 import（merge-only，不删除、不覆盖现有订阅）。
 * 文件大小前端第一道拦截（> 2 MiB 不发请求），BFF 同规则兜底。
 * mutation 后只 invalidate（invalidateSubscriptionState），不做
 * optimistic updates；结果全部来自 server-confirmed 响应。 */

import { useState } from 'react'
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
  const previewMutation = useOpmlPreviewMutation()
  const importMutation = useOpmlImportMutation()

  const busy =
    previewMutation.isPending || importMutation.isPending || result !== null

  function reset() {
    setFile(null)
    setLocalError(null)
    setResult(null)
    previewMutation.reset()
    importMutation.reset()
  }

  function selectFile(selected: File) {
    setLocalError(null)
    setResult(null)
    if (selected.size > OPML_MAX_BYTES) {
      // 本地拦截：不发请求（BFF 侧同规则兜底）
      setFile(null)
      previewMutation.reset()
      setLocalError('OPML 文件超过 2 MiB 上限。')
      return
    }
    setFile(selected)
    previewMutation.mutate(selected)
  }

  function confirmImport() {
    if (file === null || busy) return
    importMutation.mutate(file, { onSuccess: (r) => setResult(r) })
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
    selectFile,
    confirmImport,
    reset,
  }
}
