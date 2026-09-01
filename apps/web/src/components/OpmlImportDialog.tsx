/** OpmlImportDialog — 0013 Gate 4：订阅页的 OPML 导入入口（移动外壳）。
 *
 * 严格 preview-before-mutation：选择文件后必须先看到真实预览摘要
 * （BFF 无副作用解析），人工点「确认导入」才发生写入；导入后展示
 * server-confirmed 实际结果。流程逻辑全部在 lib/opml-import（与设置
 * 中心内联区块共享），本组件只负责 Dialog 外壳与 a11y。
 * - Escape 关闭（提交中禁用关闭，防误关进行中的 mutation）；
 * - 文件选择 sr-only input + label 关联，44px 触控目标。 */

import { useEffect } from 'react'
import { Upload } from 'lucide-react'
import {
  OpmlErrorCard,
  OpmlPreviewCard,
  OpmlResultCard,
} from './OpmlImportFlow'
import { useOpmlImportFlow } from '../lib/opml-import'
import { Button } from './ui/Button'
import { Dialog } from './ui/Dialog'
import { Skeleton } from './ui/Skeleton'

export default function OpmlImportDialog({
  open,
  onClose,
}: {
  open: boolean
  onClose: () => void
}) {
  const flow = useOpmlImportFlow()

  // 打开时重置全部本地状态（上一次会话不留残留）
  useEffect(() => {
    if (open) flow.reset()
    // reset 是流程 hook 的稳定方法；依赖只看 open
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  function close() {
    if (flow.busy) return // 提交中不允许误关
    onClose()
  }

  const canConfirm =
    flow.file !== null && flow.preview !== null && flow.preview.newFeeds > 0 && !flow.busy

  return (
    <Dialog
      open={open}
      onClose={close}
      title="导入 OPML"
      fullscreenOnMobile
      panelClassName="max-w-lg"
      footer={
        flow.result !== null ? (
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

        {flow.importPending && (
          <p role="status" className="text-sm text-[var(--lumi-text-secondary)]">
            正在导入，请勿关闭窗口…
          </p>
        )}

        {flow.result !== null && <OpmlResultCard result={flow.result} />}
      </div>
    </Dialog>
  )
}
