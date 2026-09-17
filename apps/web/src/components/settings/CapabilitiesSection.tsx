/** CapabilitiesSection — F34：能力可用性页。
 *
 * 统一说明本实例各能力的真实可用状态与「还缺什么」。每一项区分：
 * - 已配置（静态配置存在，如 AI base URL / Vault 路径）
 * - 已探测（实际查询过服务端状态端点，如 FreshRSS 健康、RAG 状态）
 * 不在打开页面时下载模型、不发起任何收费调用；查询全部复用既有
 * 状态端点（operations / rag / obsidian / AI 设置 / FreshRSS 订阅）。 */

import { useAiSettings, useObsidianStatus, useOperationsStatus, useRagStatus } from '../../api/queries'

type Level = 'ok' | 'unconfigured' | 'down' | 'unknown'

interface Capability {
  key: string
  label: string
  level: Level
  /** 静态配置 or 实际探测（F34 要求两者可区分） */
  basis: 'probed' | 'configured'
  detail: string
}

const LEVEL_LABEL: Record<Level, string> = {
  ok: '可用',
  unconfigured: '未配置',
  down: '不可用',
  unknown: '未知',
}

function Row({ cap }: { cap: Capability }) {
  return (
    <li className="flex min-h-10 flex-wrap items-center justify-between gap-2 py-1">
      <div className="min-w-0">
        <div className="text-sm text-[var(--lumi-text-primary)]">{cap.label}</div>
        <div className="text-xs text-[var(--lumi-text-tertiary)]">{cap.detail}</div>
      </div>
      <span
        className={cap.level === 'ok' ? 'text-xs text-[var(--lumi-accent-text)]' : 'text-xs text-[var(--lumi-text-tertiary)]'}
        data-capability-state={cap.level}
      >
        {LEVEL_LABEL[cap.level]}
        <span className="ml-1 text-[var(--lumi-text-tertiary)]">
          （{cap.basis === 'probed' ? '已探测' : '按配置'}）
        </span>
      </span>
    </li>
  )
}

export function CapabilitiesSection() {
  const operations = useOperationsStatus()
  const ai = useAiSettings()
  const rag = useRagStatus()
  const obsidian = useObsidianStatus()

  const aiValues = ai.data
  const aiConfigured = Boolean(aiValues && aiValues['ai.base_url'] && aiValues['ai.model'])
  const freshrss = operations.data?.freshrss as
    | { status?: string; configured?: boolean }
    | undefined

  const capabilities: Capability[] = [
    {
      key: 'rss',
      label: 'RSS 采集（FreshRSS）',
      level: freshrss?.status === 'healthy' ? 'ok' : freshrss?.configured ? 'down' : 'unconfigured',
      basis: 'probed',
      detail:
        freshrss?.status === 'healthy'
          ? '自动采集由 FreshRSS 容器 cron 负责（CRON_MIN）'
          : '需要配置 FreshRSS 连接并确认容器 cron 已启用',
    },
    {
      key: 'ai',
      label: '云端 AI（GPT/翻译/对话）',
      level: aiConfigured ? 'ok' : 'unconfigured',
      basis: 'configured',
      detail: aiConfigured
        ? `模型：${String(aiValues?.['ai.model'])}（调用费用由服务端产生）`
        : '缺少 base URL 或模型；API 密钥保存在服务端',
    },
    {
      key: 'rag',
      label: '语义检索（RAG）',
      level: rag.data?.available ? 'ok' : rag.data?.enabled ? 'down' : 'unconfigured',
      basis: 'probed',
      detail: rag.data?.available
        ? '索引可用（单文件 sqlite-vec，无外部向量库）'
        : '可在 AI 设置中开启；首次建立索引需要时间',
    },
    {
      key: 'obsidian',
      label: 'Obsidian 库（只读）',
      level: obsidian.data?.configured ? 'ok' : 'unconfigured',
      basis: 'configured',
      detail: obsidian.data?.configured
        ? 'Vault 路径已配置（只读投影，不回写）'
        : '未配置 Vault 路径',
    },
    {
      key: 'snapshot',
      label: '网页快照（monolith）',
      level: 'unknown',
      basis: 'probed',
      detail: '随首次快照动作探测；未安装时保存快照会得到明确失败说明',
    },
  ]

  return (
    <div className="py-2">
      <ul className="flex flex-col divide-y divide-[var(--lumi-separator)]">
        {capabilities.map((cap) => (
          <Row key={cap.key} cap={cap} />
        ))}
      </ul>
      <p className="mt-2 text-xs text-[var(--lumi-text-tertiary)]">
        本页只读，不会为探测能力产生任何费用或下载任何模型。
      </p>
    </div>
  )
}
