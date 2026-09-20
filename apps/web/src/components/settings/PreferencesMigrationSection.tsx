/** PreferencesMigrationSection — F32：非敏感偏好迁移。
 *
 * 导出/导入「可迁移 UI 偏好」（PORTABLE_KEYS：阅读排版、外观、筛选等
 * 纯展示偏好），供更换设备或实例使用：
 * - 导出 = 版本化 JSON（schemaVersion/kind/exportedAt + values），
 *   只含偏好，绝不含认证、SMTP、Webhook 或 AI 密钥；
 * - 导入 = 选文件 → 与当前值 diff 预览 → 用户确认后应用；
 * - 与完整备份用途分开（完整备份走「数据控制」的备份引擎）。
 */

import { useRef, useState } from 'react'

import { portableSettings, portableToPatch, useAppSettings } from '../../store/app-settings'
import { Button } from '../ui/Button'

const SCHEMA_VERSION = 1

interface DiffRow {
  key: string
  from: unknown
  to: unknown
  /** F040：旧 schema 字段级兼容映射（old→new） */
  mappedFrom?: string
  /** F040：无法映射的旧字段（列出跳过原因，不整体拒绝） */
  skipped?: string
}

function formatValue(value: unknown): string {
  if (value === undefined || value === null) return '（空）'
  return String(value)
}

export function PreferencesMigrationSection() {
  const settings = useAppSettings((s) => s.settings)
  const update = useAppSettings((s) => s.update)
  const fileRef = useRef<HTMLInputElement | null>(null)
  const [pending, setPending] = useState<DiffRow[] | null>(null)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [error, setError] = useState<string | null>(null)
  const [applied, setApplied] = useState(false)

  function handleExport() {
    const payload = {
      schemaVersion: SCHEMA_VERSION,
      kind: 'lumirss-preferences',
      exportedAt: new Date().toISOString(),
      values: portableSettings(settings),
    }
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `lumirss-preferences-${new Date().toISOString().slice(0, 10)}.json`
    anchor.click()
    URL.revokeObjectURL(url)
  }

  function handleImportClick() {
    setError(null)
    setApplied(false)
    fileRef.current?.click()
  }

  function handleFile(file: File) {
    file
      .text()
      .then((text) => {
        const parsed = JSON.parse(text) as {
          schemaVersion?: number
          kind?: string
          values?: Record<string, unknown>
        }
        if (parsed.kind !== 'lumirss-preferences' || parsed.schemaVersion !== SCHEMA_VERSION) {
          setError('不是有效的 LumiRSS 偏好文件（kind/schemaVersion 不匹配）。')
          setPending(null)
          return
        }
        const patch = portableToPatch(parsed.values ?? {})
        const current = portableSettings(settings)
        const rows: DiffRow[] = []
        for (const [key, to] of Object.entries(patch)) {
          const from = (current as Record<string, unknown>)[key]
          if (from !== to) rows.push({ key, from, to })
        }
        // F040：旧 schema 文件的字段级兼容映射（识别已知旧字段名→新字段）。
        const LEGACY_ALIASES: Record<string, string> = {
          readerWidth: 'readerContentWidth',
          readingTheme: 'readerBackground',
          fontFamily: 'readerFontFamily',
          fontSize: 'readerFontSize',
        }
        const incoming = parsed.values ?? {}
        for (const [oldKey, newKey] of Object.entries(LEGACY_ALIASES)) {
          if (oldKey in incoming && !(newKey in incoming)) {
            rows.push({
              key: newKey,
              from: (current as Record<string, unknown>)[newKey],
              to: incoming[oldKey],
              mappedFrom: oldKey,
            })
          }
        }
        for (const key of Object.keys(incoming)) {
          if (!(key in (current as Record<string, unknown>)) && !(key in LEGACY_ALIASES)) {
            rows.push({ key, from: null, to: incoming[key], skipped: '本地设置无此字段' })
          }
        }
        // 默认勾选：本地缺失或不同的项（rows 本身就是「将变化」项）
        setSelected(new Set(rows.filter((row) => !row.skipped).map((row) => row.key)))
        setPending(rows)
      })
      .catch(() => {
        setError('文件无法解析（需 JSON）。')
        setPending(null)
      })
  }

  function applyPending() {
    if (!pending) return
    const patch: Record<string, unknown> = {}
    // F040：仅应用所选（未选项保持原值）
    for (const row of pending) {
      if (row.skipped) continue
      if (selected.has(row.key)) patch[row.key] = row.to
    }
    update(patch as Parameters<typeof update>[0])
    setApplied(true)
    setPending(null)
  }

  return (
    <div className="flex flex-col gap-2 py-3">
      <div className="text-sm font-medium text-[var(--lumi-text-primary)]">偏好迁移</div>
      <p className="text-xs text-[var(--lumi-text-tertiary)]">
        导出阅读排版与界面偏好为版本化 JSON，可在另一台设备导入。只含偏好，不含认证、
        SMTP、Webhook 或 AI 密钥；与完整备份用途分开。
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="secondary" size="sm" onClick={handleExport}>
          导出偏好
        </Button>
        <Button variant="secondary" size="sm" onClick={handleImportClick}>
          导入偏好
        </Button>
        <input
          ref={fileRef}
          type="file"
          accept="application/json,.json"
          className="hidden"
          aria-label="选择偏好文件"
          onChange={(e) => {
            const file = e.target.files?.[0]
            if (file) handleFile(file)
            e.target.value = ''
          }}
        />
      </div>
      {error ? (
        <p role="alert" className="text-xs text-[var(--lumi-danger)]">
          {error}
        </p>
      ) : null}
      {applied ? (
        <p className="text-xs text-[var(--lumi-text-secondary)]" role="status">
          偏好已应用。
        </p>
      ) : null}
      {pending ? (
        <div className="rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] p-2.5">
          <p className="mb-1 text-xs font-medium text-[var(--lumi-text-primary)]">
            将修改 {pending.length} 项偏好：
          </p>
          <ul className="mb-2 flex max-h-40 flex-col gap-0.5 overflow-y-auto">
            {pending.map((row) =>
              row.skipped ? (
                <li key={row.key} className="text-xs text-[var(--lumi-text-tertiary)]">
                  跳过 {row.key}（{row.skipped}）
                </li>
              ) : (
                <li key={row.key} className="text-xs text-[var(--lumi-text-secondary)]">
                  <label className="flex items-center gap-1.5">
                    <input
                      type="checkbox"
                      checked={selected.has(row.key)}
                      onChange={(e) => {
                        const next = new Set(selected)
                        if (e.target.checked) next.add(row.key)
                        else next.delete(row.key)
                        setSelected(next)
                      }}
                      aria-label={`应用 ${row.key}`}
                    />
                    {row.key}
                    {row.mappedFrom ? `（将转换：${row.mappedFrom} → ${row.key}）` : ''}:{' '}
                    {formatValue(row.from)} → {formatValue(row.to)}
                  </label>
                </li>
              ),
            )}
          </ul>
          <div className="flex gap-2">
            <Button variant="primary" size="sm" onClick={applyPending}>
              仅应用所选（{selected.size}）
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setPending(null)}>
              取消
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  )
}
