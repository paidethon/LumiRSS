/** DataControlPage — 数据控制页的「配置迁移与备份」区块。
 *
 * 原「备份与恢复」独立分类并入数据控制后的承载组件。能力全部复用既有
 * 实现（不重写）：
 * - ConfigMigrationSection：浏览器本地设置导出/导入（「配置迁移」，
 *   与服务器端全量备份是两种不同能力，均真实可用）；
 * - BackupOverview：概览 + 立即创建完整备份 + 活动 job 状态；
 * - BackupHistoryCard：job 历史 + 分阶段恢复向导入口；
 * - WebDavCard：服务器端 WebDAV 目标（password 写只读）。
 *
 * OPML（订阅数据在 FreshRSS 侧）入口仍在「订阅与来源」。
 */

import { useRef, useState } from 'react'
import { Download, FileJson, Upload } from 'lucide-react'
import { normalizeSettings, useAppSettings, type AppSettings } from '../../store/app-settings'
import { Button } from '../ui/Button'
import { BackupOverview } from './backup/BackupOverview'
import { BackupHistoryCard } from './backup/BackupHistoryCard'
import { WebDavCard } from './backup/WebDavCard'

const CONFIG_SCHEMA_VERSION = 1

/** 配置迁移导出信封（纯本地设置；无任何 secret 字段）。 */
interface ConfigEnvelope {
  schemaVersion: number
  appName: 'LumiRSS'
  createdAt: string
  settings: AppSettings
}

/** 浏览器本地设置（外观 / 阅读 / 过滤规则 / 预设）导出导入。
 * 与服务器端「全量备份」不同：这里只迁移本设备 UI 配置，不涉及服务端数据。 */
function ConfigMigrationSection() {
  const settings = useAppSettings((s) => s.settings)
  const update = useAppSettings((s) => s.update)

  const [busy, setBusy] = useState(false)
  // 导入状态机：idle → inspect（摘要预览）→ done/error
  const [inspect, setInspect] = useState<{ file: File; summary: string; env: ConfigEnvelope } | null>(null)
  const [importError, setImportError] = useState<string | null>(null)
  const [importResult, setImportResult] = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  const doExport = () => {
    setBusy(true)
    try {
      const env: ConfigEnvelope = {
        schemaVersion: CONFIG_SCHEMA_VERSION,
        appName: 'LumiRSS',
        createdAt: new Date().toISOString(),
        settings: { ...settings },
      }
      const blob = new Blob([JSON.stringify(env, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `LumiRSS-config-${new Date().toISOString().slice(0, 10)}.json`
      a.click()
      URL.revokeObjectURL(url)
    } finally {
      setBusy(false)
    }
  }

  const inspectFile = async (file: File) => {
    setImportError(null)
    setImportResult(null)
    try {
      const env = JSON.parse(await file.text()) as ConfigEnvelope
      // validate-before-mutate：信封校验在任何写入之前
      if (env.schemaVersion !== CONFIG_SCHEMA_VERSION || env.appName !== 'LumiRSS' || !env.settings) {
        throw new Error('envelope')
      }
      const parts = [
        `创建时间 ${new Date(env.createdAt).toLocaleString()}`,
        `设置 ${Object.keys(env.settings).length} 项`,
        `过滤规则 ${env.settings.filterRules?.length ?? 0} 条`,
        `阅读预设 ${env.settings.readerPresets?.length ?? 0} 套`,
      ]
      setInspect({ file, env, summary: parts.join(' · ') })
    } catch {
      setImportError('导入失败：文件不是有效的 LumiRSS 配置备份')
    }
  }

  const doRestore = () => {
    if (!inspect) return
    setImportError(null)
    setBusy(true)
    try {
      const env = inspect.env
      // normalize 全量校验（非法值回退默认——validate 通过才写入）。
      // 旧备份里已退役的字段（如早期浏览器端翻译配置）不是当前 schema
      // 字段，normalize 直接丢弃。
      const restored = normalizeSettings({ ...env.settings })
      // 部分字段保留本机状态：布局宽度/折叠（设备相关）
      const merged = normalizeSettings({
        ...restored,
        sidebarWidth: settings.sidebarWidth,
        sidebarCollapsed: settings.sidebarCollapsed,
        timelineWidth: settings.timelineWidth,
        timelineCollapsed: settings.timelineCollapsed,
      })
      update(merged)
      setInspect(null)
      setImportResult(
        `恢复完成：${restored.filterRules.length} 条过滤规则、${restored.readerPresets.length} 套自定义预设`,
      )
    } catch {
      setImportError('恢复失败')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-3.5">
      <div className="flex items-center gap-2">
        <FileJson aria-hidden className="size-4 shrink-0 text-[var(--lumi-text-tertiary)]" />
        <h3 className="text-sm font-medium text-[var(--lumi-text-primary)]">配置迁移（本设备 UI 设置）</h3>
      </div>
      <p className="mt-1 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
        导出 / 导入浏览器本地设置：外观、阅读排版、过滤规则与阅读预设（JSON 文件，可跨设备迁移）。
        与下方服务器端全量备份不同——这里不包含订阅、文章状态或服务端数据，也不含任何 API Key。
      </p>

      <div className="mt-3 flex flex-wrap gap-2">
        <Button size="sm" variant="secondary" onClick={doExport} disabled={busy}>
          <Download aria-hidden className="size-3.5" />
          导出配置
        </Button>
        <Button size="sm" variant="secondary" onClick={() => fileRef.current?.click()}>
          <Upload aria-hidden className="size-3.5" />
          导入配置
        </Button>
        <input
          ref={fileRef}
          type="file"
          accept="application/json"
          className="sr-only"
          aria-label="选择配置迁移文件"
          onChange={(e) => {
            const f = e.target.files?.[0]
            if (f) void inspectFile(f)
            e.target.value = ''
          }}
        />
      </div>

      {inspect && (
        <div className="mt-3 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-accent)] p-3">
          <p className="text-xs leading-relaxed text-[var(--lumi-text-primary)]">
            {inspect.file.name}
          </p>
          <p className="mt-1 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
            {inspect.summary}
          </p>
          <div className="mt-2.5 flex gap-2">
            <Button size="sm" onClick={doRestore} disabled={busy}>
              确认恢复
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setInspect(null)}>
              取消
            </Button>
          </div>
        </div>
      )}

      {importError && <p role="alert" className="mt-2 text-xs text-[var(--lumi-danger)]">{importError}</p>}
      {importResult && (
        <p role="status" className="mt-2 text-xs text-[var(--lumi-text-secondary)]">{importResult}</p>
      )}
    </div>
  )
}

/** 数据控制页底部区块：配置迁移 → 完整备份 → 备份历史/恢复 → WebDAV。 */
export function DataBackupSection() {
  return (
    <div className="flex flex-col gap-4 py-1">
      <ConfigMigrationSection />
      <BackupOverview />
      <BackupHistoryCard />
      <WebDavCard />
    </div>
  )
}
