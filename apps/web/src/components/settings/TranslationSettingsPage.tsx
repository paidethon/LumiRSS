/** TranslationSettingsPage — 翻译设置（0010a F2，AC23）。
 * OrigRead-Desktop SettingsPanel.tsx L419-477 复刻（inspired）：
 * 目标语言 + 显示方式 + Provider 卡片（radio 默认 + 启用开关 +
 * Endpoint + Region(MS) + API Key 密码框 + 保存状态行）。
 * 交互不变量：至少保留 1 个启用 Provider；禁用默认项时自动迁移默认。
 * 测试连接/DeepL 用量：planned·0016（需 BFF 代理）。 */

import { useState } from 'react'
import { Eye, EyeOff, Save } from 'lucide-react'
import {
  TRANSLATION_PROVIDER_DEFAULTS,
  useAppSettings,
  type TranslationProvider,
  type TranslationProviderType,
} from '../../store/app-settings'
import { Button } from '../ui/Button'
import { Switch } from '../ui/Switch'
import { cx } from '../ui/cx'

function normalizeEndpoint(url: string): string {
  const trimmed = url.trim()
  if (!trimmed) return ''
  const withScheme = /^https?:\/\//.test(trimmed) ? trimmed : `https://${trimmed}`
  return withScheme.replace(/\/+$/, '')
}

export function TranslationSettingsSection() {
  const settings = useAppSettings((s) => s.settings)
  const update = useAppSettings((s) => s.update)
  const t = settings.translationSettings

  const setProvider = (type: TranslationProviderType, patch: Partial<TranslationProvider>) => {
    const providers = t.providers.map((p) => (p.type === type ? { ...p, ...patch } : p))
    update({ translationSettings: { ...t, providers } })
  }

  /** 禁用不变量（OrigRead L73-114）：至少 1 个启用；禁用默认项时迁移。 */
  const setEnabled = (type: TranslationProviderType, enabled: boolean) => {
    let providers = t.providers.map((p) => (p.type === type ? { ...p, enabled } : p))
    if (!providers.some((p) => p.enabled)) providers = providers.map((p) => ({ ...p, enabled: true }))
    let defaultProvider = t.defaultProvider
    if (!providers.find((p) => p.type === defaultProvider)?.enabled) {
      defaultProvider = providers.find((p) => p.enabled)!.type
    }
    update({ translationSettings: { ...t, providers, defaultProvider } })
  }

  const setDefault = (type: TranslationProviderType) => {
    // 选默认自动启用该项（OrigRead 同语义）
    const providers = t.providers.map((p) => (p.type === type ? { ...p, enabled: true } : p))
    update({ translationSettings: { ...t, providers, defaultProvider: type } })
  }

  return (
    <div>
      {/* 状态说明 Banner（诚实原则：当前仅保存配置） */}
      <div className="mb-4 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-3.5 py-2.5 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
        翻译执行、测试连接与 DeepL 用量查询将在 <strong>0016 Translation</strong>{' '}
        里程碑上线（需 BFF 代理，浏览器不直连翻译服务）；当前保存的配置届时直接生效。
      </div>

      {/* 目标语言 + 显示方式 */}
      <div className="py-3">
        <label className="text-sm font-medium text-[var(--lumi-text-primary)]">目标语言</label>
        <input
          type="text"
          value={t.targetLanguage}
          aria-label="目标语言"
          onChange={(e) =>
            update({
              translationSettings: { ...t, targetLanguage: e.target.value.slice(0, 16) },
            })
          }
          placeholder="zh-CN / zh-TW / en / ja …"
          className="mt-2 w-44 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2.5 py-1.5 text-sm text-[var(--lumi-text-primary)]"
        />
      </div>
      <div className="py-3">
        <label className="text-sm font-medium text-[var(--lumi-text-primary)]">显示方式</label>
        <div className="mt-2 flex gap-1.5">
          {(
            [
              ['translated', '仅译文'],
              ['bilingual', '双语对照'],
            ] as const
          ).map(([value, label]) => (
            <button
              key={value}
              type="button"
              aria-pressed={t.displayMode === value}
              onClick={() => update({ translationSettings: { ...t, displayMode: value } })}
              className={cx(
                'rounded-[var(--lumi-radius-md)] border px-3 py-1.5 text-xs transition-colors duration-[var(--lumi-motion-fast)]',
                t.displayMode === value
                  ? 'border-[var(--lumi-accent)] bg-[var(--lumi-accent-soft)] text-[var(--lumi-accent)]'
                  : 'border-[var(--lumi-border)] text-[var(--lumi-text-secondary)] hover:bg-[var(--lumi-surface-hover)]',
              )}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* Provider 卡片 × 3（OrigRead provider-card 模式） */}
      {t.providers.map((p) => (
        <ProviderCard
          key={p.type}
          provider={p}
          isDefault={t.defaultProvider === p.type}
          onSetDefault={() => setDefault(p.type)}
          onSetEnabled={(v) => setEnabled(p.type, v)}
          onChange={(patch) => setProvider(p.type, patch)}
        />
      ))}
    </div>
  )
}

function ProviderCard({
  provider,
  isDefault,
  onSetDefault,
  onSetEnabled,
  onChange,
}: {
  provider: TranslationProvider
  isDefault: boolean
  onSetDefault: () => void
  onSetEnabled: (v: boolean) => void
  onChange: (patch: Partial<TranslationProvider>) => void
}) {
  const meta = TRANSLATION_PROVIDER_DEFAULTS[provider.type]
  // 本地草稿：凭据须显式保存（OrigRead dirty 禁测语义）
  const [draftKey, setDraftKey] = useState(provider.apiKey)
  const [showKey, setShowKey] = useState(false)
  const keyDirty = draftKey !== provider.apiKey

  return (
    <div
      className={cx(
        'mb-3 rounded-[var(--lumi-radius-md)] border p-3.5',
        isDefault
          ? 'border-[var(--lumi-accent)]'
          : 'border-[var(--lumi-border)]',
      )}
    >
      <div className="flex items-center gap-2.5">
        {/* radio 默认 */}
        <input
          type="radio"
          name="translation-default-provider"
          checked={isDefault}
          onChange={onSetDefault}
          aria-label={`默认 Provider：${meta.label}`}
          className="size-4 accent-[var(--lumi-accent)]"
        />
        <span className="text-sm font-medium text-[var(--lumi-text-primary)]">{meta.label}</span>
        {isDefault && (
          <span className="rounded-[var(--lumi-radius-full)] bg-[var(--lumi-accent-soft)] px-1.5 py-0.5 text-[10px] text-[var(--lumi-accent)]">
            默认
          </span>
        )}
        <div className="ml-auto">
          <Switch
            checked={provider.enabled}
            onCheckedChange={onSetEnabled}
            label={`启用 ${meta.label}`}
          />
        </div>
      </div>

      {/* Endpoint（microsoft/deepl 预设只读展示；dlx 自填） */}
      <div className="mt-2.5">
        <label className="text-xs text-[var(--lumi-text-secondary)]">Endpoint</label>
        {provider.type === 'dlx' ? (
          <input
            type="text"
            value={provider.endpoint}
            aria-label={`${meta.label} Endpoint`}
            onChange={(e) => onChange({ endpoint: e.target.value })}
            onBlur={(e) => onChange({ endpoint: normalizeEndpoint(e.target.value) })}
            placeholder="https://your-deeplx.example.com/translate"
            className="mt-1 w-full rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2.5 py-1.5 font-mono text-xs text-[var(--lumi-text-primary)]"
          />
        ) : (
          <p className="mt-1 font-mono text-xs text-[var(--lumi-text-tertiary)]">
            {meta.endpoint || provider.endpoint}
          </p>
        )}
      </div>

      {/* Region（仅 Microsoft） */}
      {provider.type === 'microsoft' && (
        <div className="mt-2.5">
          <label className="text-xs text-[var(--lumi-text-secondary)]">Region（Azure 区域）</label>
          <input
            type="text"
            value={provider.region}
            aria-label="Microsoft Region"
            onChange={(e) => onChange({ region: e.target.value.slice(0, 32) })}
            placeholder="eastasia / global …"
            className="mt-1 w-44 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2.5 py-1.5 text-xs text-[var(--lumi-text-primary)]"
          />
        </div>
      )}

      {/* API Key：密码框 + 眼睛 + 保存按钮 + 状态行（OrigRead SecretKeyEditor 模式） */}
      <div className="mt-2.5">
        <label className="text-xs text-[var(--lumi-text-secondary)]">API Key</label>
        <div className="mt-1 flex items-center gap-2">
          <input
            type={showKey ? 'text' : 'password'}
            value={draftKey}
            aria-label={`${meta.label} API Key`}
            onChange={(e) => setDraftKey(e.target.value)}
            placeholder={provider.type === 'dlx' ? '可选 token' : '必填'}
            className="min-w-0 flex-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2.5 py-1.5 font-mono text-xs text-[var(--lumi-text-primary)]"
          />
          <button
            type="button"
            onClick={() => setShowKey((v) => !v)}
            aria-label={showKey ? '隐藏 API Key' : '显示 API Key'}
            className="flex size-8 shrink-0 items-center justify-center rounded-[var(--lumi-radius-md)] text-[var(--lumi-text-tertiary)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)]"
          >
            {showKey ? <EyeOff aria-hidden className="size-4" /> : <Eye aria-hidden className="size-4" />}
          </button>
          <Button
            size="sm"
            variant="secondary"
            disabled={!keyDirty}
            onClick={() => onChange({ apiKey: draftKey.trim() })}
          >
            <Save aria-hidden className="size-3.5" />
            保存
          </Button>
        </div>
        <p className="mt-1 text-[11px] text-[var(--lumi-text-tertiary)]">
          {keyDirty
            ? '未保存（修改后需点保存）'
            : provider.apiKey
              ? `已存储 ${provider.apiKey.length} 字符`
              : '未设置'}
        </p>
      </div>

      {/* 测试连接：planned·0016（disabled + 徽标） */}
      <div className="mt-2.5 flex items-center gap-2">
        <Button size="sm" variant="ghost" disabled>
          测试连接
        </Button>
        {provider.type === 'deepl' && (
          <Button size="sm" variant="ghost" disabled>
            查询额度
          </Button>
        )}
        <span className="rounded-[var(--lumi-radius-full)] bg-[var(--lumi-surface-selected)] px-2 py-0.5 text-[11px] text-[var(--lumi-text-tertiary)]">
          planned · 0016
        </span>
      </div>
    </div>
  )
}
