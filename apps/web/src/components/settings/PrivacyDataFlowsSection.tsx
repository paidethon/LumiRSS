/** PrivacyDataFlowsSection — N181：逐来源数据外发清单。
 *
 * 数据全部来自 GET /api/v1/privacy/data-flows（服务端从「当前真实配置」
 * 推导，只读、无网络请求）：每个能力一条——已配置 → 显示目标主机名
 * （仅主机名，绝无密钥/路径）与数据类别；未配置 → 如实显示「不发送」。
 * 本机能力（如浏览器 TTS）local=true，明确标注数据不出设备。
 */

import { useDataFlows } from '../../api/queries'
import type { DataFlowItem } from '../../api/types'
import { Skeleton } from '../ui/Skeleton'

const CAPABILITY_LABELS: Record<string, string> = {
  'ai-summary': 'AI 摘要',
  'ai-translation': 'AI 翻译',
  'ai-chat': 'AI 对话',
  libretranslate: 'LibreTranslate 翻译',
  'remote-images': '远程图片',
  tts: '语音朗读（TTS）',
  webdav: 'WebDAV 备份',
  imap: '邮件简报（IMAP 收信）',
}

function FlowRow({ flow }: { flow: DataFlowItem }) {
  const label = CAPABILITY_LABELS[flow.capability] ?? flow.capability
  return (
    <li
      className="flex min-h-10 flex-wrap items-start justify-between gap-2 py-2"
      data-data-flow={flow.capability}
    >
      <div className="min-w-0">
        <div className="text-sm text-[var(--lumi-text-primary)]">{label}</div>
        {flow.configured && (
          <div className="mt-0.5 text-xs leading-relaxed text-[var(--lumi-text-tertiary)]">
            {flow.dataCategories.join('；')}
          </div>
        )}
      </div>
      {flow.configured ? (
        <span
          className="shrink-0 text-right text-xs leading-relaxed"
          data-flow-configured=""
        >
          {flow.local ? (
            <span className="text-[var(--lumi-accent-text)]">仅本机（不外发）</span>
          ) : (
            <span className="text-[var(--lumi-text-primary)]">
              发送到 <span className="font-mono">{flow.providerHost ?? '（随条目来源）'}</span>
            </span>
          )}
        </span>
      ) : (
        <span className="shrink-0 text-xs text-[var(--lumi-text-tertiary)]" data-flow-disabled="">
          不发送
        </span>
      )}
    </li>
  )
}

export function PrivacyDataFlowsSection() {
  const flows = useDataFlows()

  return (
    <div className="py-3" data-privacy-data-flows="">
      <div className="text-sm font-medium text-[var(--lumi-text-primary)]">数据外发</div>
      <p className="mt-1 text-xs leading-relaxed text-[var(--lumi-text-tertiary)]">
        本实例各能力「会把什么数据发到哪里」的实况清单（来自当前真实配置；
        只含主机名，绝不含任何密钥）。未配置的能力不会发送任何数据。
      </p>
      {flows.isPending ? (
        <div className="mt-2 flex flex-col gap-2" aria-label="正在加载数据外发清单">
          <Skeleton className="h-9 w-full" />
          <Skeleton className="h-9 w-3/4" />
        </div>
      ) : flows.isError ? (
        <p role="alert" className="mt-2 text-xs text-[var(--lumi-danger)]">
          数据外发清单加载失败：{flows.error instanceof Error ? flows.error.message : '请稍后重试。'}
        </p>
      ) : (
        <ul className="mt-1 flex flex-col divide-y divide-[var(--lumi-separator)]">
          {flows.data?.flows.map((flow) => <FlowRow key={flow.capability} flow={flow} />)}
        </ul>
      )}
    </div>
  )
}
