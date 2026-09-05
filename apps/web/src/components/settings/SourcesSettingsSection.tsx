/** SourcesSettingsSection — 0013 Gate 4：设置 → 订阅与来源。
 *
 * 全断点可用的订阅管理入口（桌面无订阅页 shell，0011 已知缺口；
 * 本页在 SettingsModal 内联渲染，无嵌套 Dialog 问题）：
 * - OPML 导出：BFF 代理 FreshRSS subscription/export，浏览器不接触
 *   FreshRSS 凭据；内容只有订阅 + 分类（无设置 dump / API key）。
 * - OPML 导入：完整 preview → confirm → result 闭环（OpmlImportFlow）。
 * - FreshRSS 高级逃生入口：仅当服务端显式配置了浏览器可达的
 *   FRESHRSS_PUBLIC_URL 才渲染「在 FreshRSS 中管理」；未配置 →
 *   诚实说明，不渲染假链接。
 * - 服务状态只报告有真实依据的错误（订阅列表请求的 error type），
 *   不编造「健康 98%」之类的伪指标。 */

/** FreshRSS 状态卡：真实服务状态 + 订阅源数量 + Lumi 内管理入口。
 *
 * 高级管理分两层：
 * - Lumi 内（订阅中心）：添加/取消订阅、移动订阅、分类重命名、OPML
 *   导入导出——全部经 BFF 控制平面真实可用，一键直达；
 * - FreshRSS 原生（可选逃生入口）：仅当服务端显式配置了浏览器可达的
 *   FRESHRSS_PUBLIC_URL 才渲染链接；未配置不渲染假链接。 */

import { AlertCircle, CheckCircle2, Download, ExternalLink, Upload } from 'lucide-react'
import { useOperationsStatus, useSubscriptions } from '../../api/queries'
import type { ApiError } from '../../api/client'
import {
  OpmlErrorCard,
  OpmlPreviewCard,
  OpmlResultCard,
} from '../OpmlImportFlow'
import { useFreshRssUiUrl } from '../../api/queries'
import { useOpmlExportFlow, useOpmlImportFlow } from '../../lib/opml-import'
import { managementErrorText } from '../../lib/management-errors'
import { useReaderUi } from '../../store/reader-ui'
import { requestCloseSettings } from './settings-bridge'
import { Button } from '../ui/Button'
import { Skeleton } from '../ui/Skeleton'

/** OPML 导出：下载经 BFF 代理的 FreshRSS 导出（loading/成功/失败三态；
 * 0014a：状态机收敛到 lib/opml-import 的 useOpmlExportFlow 与订阅管理页共享）。 */
function OpmlExportBlock() {
  const { busy, error, done, exportOnce } = useOpmlExportFlow()

  return (
    <div className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-3.5">
      <p className="text-sm font-medium text-[var(--lumi-text-primary)]">导出订阅（OPML）</p>
      <p className="mt-1 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
        从 FreshRSS 导出全部订阅与分类。文件只包含订阅列表，不含设置、密钥、阅读记录或收藏。
      </p>
      <div className="mt-3 flex items-center gap-2">
        <Button size="sm" onClick={exportOnce} disabled={busy}>
          <Download aria-hidden className="size-3.5" />
          {busy ? '导出中…' : '导出 OPML'}
        </Button>
        {done && (
          <span role="status" className="flex items-center gap-1 text-xs text-[var(--lumi-text-secondary)]">
            <CheckCircle2 aria-hidden className="size-3.5 text-[var(--lumi-accent-text)]" />
            已开始下载
          </span>
        )}
      </div>
      {error !== null && (
        <p role="alert" className="mt-2 flex items-center gap-1.5 text-xs text-[var(--lumi-danger)]">
          <AlertCircle aria-hidden className="size-3.5 shrink-0" />
          {error}
        </p>
      )}
    </div>
  )
}

/** OPML 导入：内联 preview → confirm → result 闭环（共享 OpmlImportFlow）。 */
function OpmlImportBlock() {
  const flow = useOpmlImportFlow()
  const canConfirm =
    flow.file !== null && flow.preview !== null && flow.preview.newFeeds > 0 && !flow.busy

  return (
    <div className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-3.5">
      <p className="text-sm font-medium text-[var(--lumi-text-primary)]">导入订阅（OPML）</p>
      <p className="mt-1 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
        选择 OPML 文件后先预览（数量 / 分类 / 重复），确认后才写入。导入为合并：只新增
        订阅，不删除、不覆盖任何现有订阅。
      </p>
      {!flow.result && (
        <label htmlFor="sources-opml-file" className="mt-3 block">
          <span className="flex min-h-11 items-center gap-2 text-sm text-[var(--lumi-text-primary)]">
            <Upload aria-hidden className="size-4" />
            选择 OPML 文件
          </span>
          <input
            id="sources-opml-file"
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
        </label>
      )}
      <div className="mt-3 flex flex-col gap-3">
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
            正在导入，请稍候…
          </p>
        )}
        {flow.result !== null && (
          <>
            <OpmlResultCard result={flow.result} />
            <div>
              <Button size="sm" variant="secondary" onClick={flow.reset}>
                再导入一个文件
              </Button>
            </div>
          </>
        )}
        {!flow.result && flow.preview !== null && (
          <div className="flex gap-2">
            <Button size="sm" onClick={flow.confirmImport} disabled={!canConfirm}>
              确认导入
            </Button>
            <Button size="sm" variant="ghost" onClick={flow.reset} disabled={flow.busy}>
              重新选择
            </Button>
          </div>
        )}
      </div>
    </div>
  )
}

/** FreshRSS 服务状态文案（operations/status 的真实探测结果）。 */
function useFreshRssServiceStatus(): { loading: boolean; label: string; healthy: boolean } {
  const operations = useOperationsStatus()
  const freshrss = operations.data?.freshrss
  if (operations.isPending || freshrss === undefined) {
    return { loading: true, label: '', healthy: false }
  }
  switch (freshrss.status) {
    case 'healthy':
      return { loading: false, label: '正常', healthy: true }
    case 'unauthenticated':
      return { loading: false, label: '可达（凭据待配置）', healthy: true }
    default:
      return { loading: false, label: '状态异常', healthy: false }
  }
}

/** FreshRSS 状态 + Lumi 内管理入口 + 可选逃生链接。 */
function FreshRssStatusBlock() {
  const subscriptions = useSubscriptions()
  const ui = useFreshRssUiUrl()
  const service = useFreshRssServiceStatus()
  const selectSection = useReaderUi((s) => s.selectSection)

  // 只在有真实请求结果时报告；加载中不显示任何「状态」。
  let statusNode: React.ReactNode = null
  if (subscriptions.isError) {
    statusNode = (
      <p
        role="alert"
        className="mt-2 flex items-start gap-1.5 text-xs leading-relaxed text-[var(--lumi-danger)]"
      >
        <AlertCircle aria-hidden className="mt-0.5 size-3.5 shrink-0" />
        {managementErrorText((subscriptions.error as ApiError) ?? {}).title}
      </p>
    )
  } else if (subscriptions.isSuccess && subscriptions.data !== undefined) {
    statusNode = (
      <div className="mt-2 flex flex-col gap-1">
        <p
          role="status"
          className="flex items-center gap-1.5 text-xs text-[var(--lumi-text-secondary)]"
        >
          <CheckCircle2 aria-hidden className="size-3.5 shrink-0 text-[var(--lumi-accent-text)]" />
          {service.loading
            ? `当前 ${subscriptions.data.length} 个订阅源`
            : `服务${service.label}，当前 ${subscriptions.data.length} 个订阅源`}
        </p>
        {!service.loading && !service.healthy && (
          <p role="alert" className="flex items-start gap-1.5 text-xs leading-relaxed text-[var(--lumi-danger)]">
            <AlertCircle aria-hidden className="mt-0.5 size-3.5 shrink-0" />
            FreshRSS 服务状态异常，请检查服务端部署（docker compose ps）。
          </p>
        )}
      </div>
    )
  }

  return (
    <div className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-3.5">
      <p className="text-sm font-medium text-[var(--lumi-text-primary)]">FreshRSS</p>
      <p className="mt-1 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
        订阅数据由 FreshRSS 托管，Lumi 通过 BFF 控制平面读写（凭据不出服务端）。
      </p>
      {statusNode}
      {/* Lumi 内高级管理：订阅中心真实可用的一站式入口 */}
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Button
          size="sm"
          variant="secondary"
          onClick={() => {
            selectSection('subscriptions')
            requestCloseSettings()
          }}
        >
          打开订阅中心
        </Button>
        <span className="text-xs leading-relaxed text-[var(--lumi-text-tertiary)]">
          添加 / 取消订阅、移动分类、重命名分类与 OPML 导入导出都在订阅中心完成。
        </span>
      </div>
      {/* FreshRSS 原生逃生入口：只有显式配置的浏览器可达 public URL 才渲染 */}
      {ui.data?.url != null && (
        <p className="mt-2.5">
          <a
            href={ui.data.url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 text-xs text-[var(--lumi-accent-text)] hover:underline"
          >
            高级：在 FreshRSS 中管理
            <ExternalLink aria-hidden className="size-3" />
          </a>
        </p>
      )}
    </div>
  )
}

export function SourcesSettingsSection() {
  return (
    <div className="flex flex-col gap-4 py-1">
      <OpmlExportBlock />
      <OpmlImportBlock />
      <FreshRssStatusBlock />
    </div>
  )
}
