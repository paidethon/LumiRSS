/** RssHubSettingsPage — RSSHub 实例管理（0010a F4，AC25）。
 * OrigRead rsshub 设置页复刻（inspired）：总开关 Banner + 实例列表
 * （启停/删除 + url·地区·维护者）+ 添加实例 + 恢复默认。
 * 测试连接 planned·0014（BFF 代理）；前端零直连 RSSHub（架构边界）。 */

import { useState } from 'react'
import { Plus, RotateCcw, Trash2 } from 'lucide-react'
import {
  BUILTIN_RSSHUB_INSTANCES,
  useAppSettings,
  type RssHubInstance,
} from '../../store/app-settings'
import { Button } from '../ui/Button'
import { Switch } from '../ui/Switch'

/** 地区代码 → 展示名（OrigRead RssHubLocation 中立代码语义）。 */
const LOCATION_LABELS: Record<string, string> = {
  US: '美国', CN: '中国', HK: '香港', GB: '英国', AE: '阿联酋', FR: '法国',
  DE: '德国', CA: '加拿大', VN: '越南', GLOBAL: '全球',
}

export function RssHubSettingsSection() {
  const settings = useAppSettings((s) => s.settings)
  const update = useAppSettings((s) => s.update)
  const r = settings.rsshubSettings

  const [newUrl, setNewUrl] = useState('')
  const [addError, setAddError] = useState<string | null>(null)

  const setInstances = (instances: RssHubInstance[]) =>
    update({ rsshubSettings: { ...r, instances } })

  /** 添加实例（OrigRead「测试并添加」语义的纯前端版：URL 校验 + 查重；
   * 连通测试 0014 BFF 代理后接入）。 */
  const addInstance = () => {
    const url = newUrl.trim()
    if (!/^https?:\/\/[\w.-]+/.test(url)) {
      setAddError('请输入合法的实例地址（https://…）')
      return
    }
    const normalized = url.replace(/\/+$/, '')
    const existing = r.instances.find((i) => i.url === normalized)
    if (existing) {
      // 已存在 → 重新启用（OrigRead 同语义）
      if (!existing.enabled) setInstances(r.instances.map((i) => (i.url === normalized ? { ...i, enabled: true } : i)))
      setNewUrl('')
      setAddError(null)
      return
    }
    setInstances([
      ...r.instances,
      {
        id: `custom-${Date.now().toString(36)}`,
        url: normalized,
        location: 'GLOBAL',
        maintainer: '自建',
        enabled: true,
        builtIn: false,
      },
    ])
    setNewUrl('')
    setAddError(null)
  }

  const restoreDefaults = () =>
    update({
      rsshubSettings: { enabled: r.enabled, instances: BUILTIN_RSSHUB_INSTANCES },
    })

  return (
    <div>
      {/* 总开关 Banner */}
      <div className="mb-4 flex items-center justify-between gap-3 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-3.5 py-2.5">
        <div>
          <p className="text-sm font-medium text-[var(--lumi-text-primary)]">RSSHub 集成</p>
          <p className="mt-0.5 text-[11px] leading-relaxed text-[var(--lumi-text-tertiary)]">
            来源发现（0014）使用服务端配置的 RSSHub 实例（RSSHUB_BASE_URL），经 BFF 代理，
            浏览器不直连 RSSHub；此处为实例清单管理。
          </p>
        </div>
        <Switch
          checked={r.enabled}
          onCheckedChange={(v) => update({ rsshubSettings: { ...r, enabled: v } })}
          label="RSSHub 总开关"
        />
      </div>

      {/* 添加实例 */}
      <div className="mb-4">
        <div className="flex items-center gap-2">
          <input
            type="text"
            value={newUrl}
            aria-label="实例地址"
            onChange={(e) => {
              setNewUrl(e.target.value)
              setAddError(null)
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter') addInstance()
            }}
            placeholder="https://your-rsshub.example.com"
            className="min-w-0 flex-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2.5 py-1.5 font-mono text-xs text-[var(--lumi-text-primary)]"
          />
          <Button size="sm" onClick={addInstance}>
            <Plus aria-hidden className="size-3.5" />
            添加
          </Button>
        </div>
        {addError && <p className="mt-1.5 text-xs text-[var(--lumi-danger)]">{addError}</p>}
        <p className="mt-1.5 text-[11px] text-[var(--lumi-text-tertiary)]">
          添加的实例仅作清单参考；来源发现使用服务端配置的实例（见服务端 RSSHUB_BASE_URL）。
        </p>
      </div>

      {/* 实例列表 */}
      <ul className="divide-y divide-[var(--lumi-separator)] rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)]">
        {r.instances.map((i) => (
          <li key={i.id} className="flex items-center gap-3 px-3.5 py-2.5">
            <div className="min-w-0 flex-1">
              <p className="truncate font-mono text-xs text-[var(--lumi-text-primary)]">{i.url}</p>
              <p className="text-[11px] text-[var(--lumi-text-tertiary)]">
                {LOCATION_LABELS[i.location] ?? i.location} · {i.maintainer || '—'}
                {i.builtIn && ' · 内置'}
              </p>
            </div>
            <Switch
              checked={i.enabled}
              onCheckedChange={(v) =>
                setInstances(r.instances.map((x) => (x.id === i.id ? { ...x, enabled: v } : x)))
              }
              label={`启用实例 ${i.url}`}
            />
            <button
              type="button"
              aria-label={`删除实例 ${i.url}`}
              onClick={() => setInstances(r.instances.filter((x) => x.id !== i.id))}
              className="flex size-8 shrink-0 items-center justify-center rounded-[var(--lumi-radius-md)] text-[var(--lumi-text-tertiary)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)] hover:text-[var(--lumi-danger)]"
            >
              <Trash2 aria-hidden className="size-4" />
            </button>
          </li>
        ))}
      </ul>

      <div className="mt-3">
        <Button size="sm" variant="ghost" onClick={restoreDefaults}>
          <RotateCcw aria-hidden className="size-3.5" />
          恢复默认（16 个内置实例）
        </Button>
      </div>
    </div>
  )
}
