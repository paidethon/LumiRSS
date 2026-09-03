/** BackupSettingsPage — 备份与恢复（0010a F5，AC26/AC27；0017 简化）。
 * OrigRead 配置备份语义复刻（inspired）：
 * - 导出：JSON 信封（schemaVersion/appName/createdAt + 全部本地设置）下载；
 * - 导入：inspect 摘要预览 → validate-before-mutate → 合并恢复；
 * - 0017：浏览器端已不存在任何 API Key（翻译/摘要/AI 全部走 BFF，
 *   key 只在服务端环境）——删除原「加密导出 API Key」流程；旧备份文件
 *   中的 translationSettings/encryptedSecrets 字段导入时被安全忽略
 *   （不会迁移进任何地方、不会打印）。
 * OPML：已实现（0013，数据在 FreshRSS 侧；导入导出入口在「订阅与来源」）。 */

import { useRef, useState } from 'react'
import { Download, Upload } from 'lucide-react'
import { normalizeSettings, useAppSettings, type AppSettings } from '../../store/app-settings'
import { Button } from '../ui/Button'

const BACKUP_SCHEMA_VERSION = 1

/** 导出信封（纯设置；无任何 secret 字段）。 */
interface BackupEnvelope {
  schemaVersion: number
  appName: 'LumiRSS'
  createdAt: string
  settings: AppSettings
}

export function BackupSettingsSection() {
  const settings = useAppSettings((s) => s.settings)
  const update = useAppSettings((s) => s.update)

  const [busy, setBusy] = useState(false)

  // 导入状态机：idle → inspect（摘要预览）→ done/error
  const [inspect, setInspect] = useState<{ file: File; summary: string; env: BackupEnvelope } | null>(null)
  const [importError, setImportError] = useState<string | null>(null)
  const [importResult, setImportResult] = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  // ---- 导出 ----
  const doExport = () => {
    setBusy(true)
    try {
      const env: BackupEnvelope = {
        schemaVersion: BACKUP_SCHEMA_VERSION,
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

  // ---- 导入：inspect（只读摘要，validate 信封） ----
  const inspectFile = async (file: File) => {
    setImportError(null)
    setImportResult(null)
    try {
      const env = JSON.parse(await file.text()) as BackupEnvelope
      // validate-before-mutate：信封校验在任何写入之前
      if (env.schemaVersion !== BACKUP_SCHEMA_VERSION || env.appName !== 'LumiRSS' || !env.settings) {
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

  // ---- 导入：确认恢复（先全部校验再写入） ----
  const doRestore = () => {
    if (!inspect) return
    setImportError(null)
    setBusy(true)
    try {
      const env = inspect.env
      // normalize 全量校验（非法值回退默认——validate 通过才写入）。
      // 旧备份的 translationSettings/encryptedSecrets 不是当前 schema
      // 字段，normalize 直接丢弃（浏览器端翻译 Key 已随 0016/0017 退役）。
      const restored = normalizeSettings({ ...env.settings })
      // 部分字段保留本机状态：布局宽度/折叠（设备相关，OrigRead 同思路）
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
    <div>
      {/* 导出 */}
      <div className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-3.5">
        <p className="text-sm font-medium text-[var(--lumi-text-primary)]">导出配置备份</p>
        <p className="mt-1 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
          包含全部本地设置、过滤规则与阅读预设（JSON，可跨设备迁移）。不包含任何
          API Key（浏览器不保存任何密钥）。
        </p>
        <div className="mt-3">
          <Button size="sm" onClick={doExport} disabled={busy}>
            <Download aria-hidden className="size-3.5" />
            导出备份
          </Button>
        </div>
      </div>

      {/* 导入 */}
      <div className="mt-4 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-3.5">
        <p className="text-sm font-medium text-[var(--lumi-text-primary)]">恢复配置</p>
        <p className="mt-1 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
          选择备份文件 → 预览摘要 → 确认恢复。恢复不删除任何本机数据
          （合并语义）；旧版备份中的浏览器端翻译配置会被安全忽略。
        </p>
        <div className="mt-3">
          <Button size="sm" variant="secondary" onClick={() => fileRef.current?.click()}>
            <Upload aria-hidden className="size-3.5" />
            选择备份文件
          </Button>
          <input
            ref={fileRef}
            type="file"
            accept="application/json"
            className="sr-only"
            onChange={(e) => {
              const f = e.target.files?.[0]
              if (f) void inspectFile(f)
              e.target.value = ''
            }}
          />
        </div>

        {/* inspect 摘要预览（写入前） */}
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

        {importError && <p className="mt-2 text-xs text-[var(--lumi-danger)]">{importError}</p>}
        {importResult && (
          <p className="mt-2 text-xs text-[var(--lumi-text-secondary)]">{importResult}</p>
        )}
      </div>

      {/* 订阅列表（OPML）：真实可用，入口在「订阅与来源」（0013；
           0014a：不再标注 planned —— OPML 导入导出已实现） */}
      <div className="mt-4 flex items-center gap-3 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-3.5">
        <div className="min-w-0 flex-1">
          <p className="text-sm text-[var(--lumi-text-primary)]">订阅列表（OPML）</p>
          <p className="mt-0.5 text-xs text-[var(--lumi-text-secondary)]">
            订阅数据存于 FreshRSS（唯一真源）；OPML 导入 / 导出经 BFF 控制平面
            真实可用（0013），入口在设置 →「订阅与来源」与订阅中心页。
          </p>
        </div>
        <span className="rounded-[var(--lumi-radius-full)] bg-[var(--lumi-surface-selected)] px-2 py-0.5 text-[11px] text-[var(--lumi-text-tertiary)]">
          已实现 · 0013
        </span>
      </div>
    </div>
  )
}
