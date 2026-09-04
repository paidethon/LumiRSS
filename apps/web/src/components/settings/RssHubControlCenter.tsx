/** RssHubControlCenter — 0018：RSSHub 真实控制面（schema 驱动 allow-list）。
 *
 * 取代 0010a 的浏览器本地 16 实例清单为「参考实例」子区，并新增：
 * - 运行时状态（服务端探测的真实 health / 延迟）；
 * - 分组配置（typed allow-list，非任意 env 编辑器）；
 * - restartRequired 语义：保存只更新 desired，UI 如实显示「重启后生效」；
 * - 路由凭据（secret 写只读：只显示「已配置/未配置」，永不回读明文）；
 * - 导出 .env 片段（非 secret 明文；secret 只渲染 key 名）。
 */

import { useMemo, useState } from 'react'
import {
  AlertCircle,
  CheckCircle2,
  Download,
  KeyRound,
  Loader2,
  RotateCcw,
  Satellite,
  Trash2,
} from 'lucide-react'
import {
  useApplyRssHubConfigMutation,
  useClearRssHubSecretMutation,
  useOperationsStatus,
  usePatchRssHubConfigMutation,
  useRssHubConfig,
  useSetRssHubSecretMutation,
} from '../../api/queries'
import type { ApiError } from '../../api/client'
import type { RssHubConfigItem } from '../../api/types'
import { Button } from '../ui/Button'
import { Select } from '../ui/Select'
import { Skeleton } from '../ui/Skeleton'
import { Switch } from '../ui/Switch'
import { cx } from '../ui/cx'

const inputClass = cx(
  'w-full min-h-9 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)]',
  'bg-[var(--lumi-surface)] px-2.5 text-sm text-[var(--lumi-text-primary)]',
  'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
)

const RUNTIME_LABELS: Record<string, string> = {
  unconfigured: '未配置',
  healthy: '正常',
  unauthenticated: '认证失败',
  unavailable: '连接失败',
}

function RuntimeCard() {
  const status = useOperationsStatus()
  const rsshub = status.data?.rsshub
  const label = rsshub ? RUNTIME_LABELS[rsshub.status] ?? rsshub.status : null

  return (
    <div className="flex items-center gap-3 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-3.5 py-2.5">
      <Satellite aria-hidden className="size-4 shrink-0 text-[var(--lumi-text-tertiary)]" />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-[var(--lumi-text-primary)]">
          RSSHub 运行时
        </p>
        <p className="mt-0.5 text-xs text-[var(--lumi-text-secondary)]">
          {status.isPending || label === null ? '正在探测…' : label}
          {typeof rsshub?.latencyMs === 'number' && ` · 延迟 ${rsshub.latencyMs} ms`}
        </p>
      </div>
      <span
        className={cx(
          'size-2.5 shrink-0 rounded-full',
          rsshub?.status === 'healthy'
            ? 'bg-[var(--lumi-accent)]'
            : 'bg-[var(--lumi-text-tertiary)]',
        )}
        aria-hidden="true"
      />
    </div>
  )
}

function SecretField({ item }: { item: RssHubConfigItem }) {
  const [value, setValue] = useState('')
  const set = useSetRssHubSecretMutation()
  const clear = useClearRssHubSecretMutation()

  return (
    <div className="flex flex-col gap-2 py-2.5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm text-[var(--lumi-text-primary)]">{item.label}</p>
          <p className="mt-0.5 text-xs leading-relaxed text-[var(--lumi-text-tertiary)]">
            {item.description}
          </p>
        </div>
        <span
          className={cx(
            'shrink-0 rounded-[var(--lumi-radius-full)] px-2 py-0.5 text-[11px]',
            item.configured
              ? 'bg-[var(--lumi-surface-selected)] text-[var(--lumi-text-secondary)]'
              : 'bg-[var(--lumi-surface)] text-[var(--lumi-text-tertiary)]',
          )}
        >
          {item.configured ? '已配置' : '未配置'}
        </span>
      </div>
      <div className="flex items-center gap-2">
        <input
          type="password"
          value={value}
          aria-label={`${item.label}（secret）`}
          placeholder={item.configured ? '输入新值以更新' : '输入值'}
          onChange={(e) => setValue(e.target.value)}
          className={inputClass}
        />
        <Button
          size="sm"
          disabled={set.isPending || !value.trim()}
          onClick={() => set.mutate({ key: item.key, value }, { onSuccess: () => setValue('') })}
        >
          {set.isPending ? <Loader2 aria-hidden className="size-3.5 animate-spin" /> : <KeyRound aria-hidden className="size-3.5" />}
          保存
        </Button>
        {item.configured && (
          <Button size="sm" variant="ghost" disabled={clear.isPending} onClick={() => clear.mutate(item.key)}>
            <Trash2 aria-hidden className="size-3.5" />
            清除
          </Button>
        )}
      </div>
    </div>
  )
}

/** 单条非 secret 配置字段；值来自 draft，编辑只改 draft，保存统一 PATCH。 */
function ConfigField({
  item,
  value,
  onChange,
}: {
  item: RssHubConfigItem
  value: number | string | boolean
  onChange: (next: number | string | boolean) => void
}) {
  if (item.secret) return <SecretField item={item} />

  if (!item.editable) {
    return (
      <div className="flex items-center justify-between gap-3 py-2.5">
        <div className="min-w-0">
          <p className="text-sm text-[var(--lumi-text-primary)]">{item.label}</p>
          <p className="mt-0.5 text-xs leading-relaxed text-[var(--lumi-text-tertiary)]">{item.description}</p>
        </div>
        <span className="shrink-0 font-mono text-xs text-[var(--lumi-text-secondary)]">
          {String(value)}
        </span>
      </div>
    )
  }

  return (
    <div className="py-2.5">
      <p className="text-sm text-[var(--lumi-text-primary)]">{item.label}</p>
      <p className="mb-1.5 mt-0.5 text-xs leading-relaxed text-[var(--lumi-text-tertiary)]">{item.description}</p>
      {item.type === 'bool' ? (
        <Switch
          checked={value === true}
          onCheckedChange={onChange}
          label={value === true ? '开启' : '关闭'}
        />
      ) : item.type === 'enum' ? (
        <Select
          aria-label={item.label}
          value={String(value)}
          options={(item.options ?? []).map((o) => ({ value: o, label: o }))}
          onChange={(e) => onChange(e.target.value)}
        />
      ) : item.type === 'int' ? (
        <input
          type="number"
          aria-label={item.label}
          value={Number(value)}
          onChange={(e) => onChange(Number(e.target.value))}
          className={inputClass}
        />
      ) : (
        <input
          type="text"
          aria-label={item.label}
          value={String(value)}
          onChange={(e) => onChange(e.target.value)}
          className={inputClass}
        />
      )}
    </div>
  )
}

export function RssHubControlCenter() {
  const config = useRssHubConfig()
  const patch = usePatchRssHubConfigMutation()
  const apply = useApplyRssHubConfigMutation()
  const [draft, setDraft] = useState<Record<string, number | string | boolean> | null>(null)
  const [error, setError] = useState<string | null>(null)

  const values = useMemo(() => {
    if (!config.data) return {}
    const map: Record<string, number | string | boolean> = {}
    for (const g of config.data.groups) {
      for (const it of g.items) {
        if (!it.secret && it.value !== undefined) map[it.key] = it.value
      }
    }
    return map
  }, [config.data])

  if (config.isError) {
    return (
      <p role="alert" className="flex items-start gap-1.5 text-sm text-[var(--lumi-danger)]">
        <AlertCircle aria-hidden className="mt-0.5 size-4 shrink-0" />
        配置加载失败：{config.error instanceof Error ? (config.error as ApiError).message : '请稍后重试。'}
      </p>
    )
  }

  if (config.data === undefined) {
    return (
      <div className="flex flex-col gap-3 py-1" aria-label="正在加载 RSSHub 配置">
        <Skeleton className="h-9 w-full" />
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-24 w-full" />
      </div>
    )
  }

  const data = config.data
  const currentDraft = draft ?? values

  const setValue = (key: string, next: number | string | boolean) => {
    setError(null)
    setDraft({ ...currentDraft, [key]: next })
  }

  const dirtyEntries = (() => {
    const entries: Record<string, number | string | boolean> = {}
    for (const [key, value] of Object.entries(currentDraft)) {
      if (values[key] !== value) entries[key] = value
    }
    return entries
  })()

  const save = () => {
    if (Object.keys(dirtyEntries).length === 0) return
    setError(null)
    patch.mutate(dirtyEntries, {
      onSuccess: () => setDraft(null),
      onError: (e) => setError(e instanceof Error ? e.message : '保存失败'),
    })
  }

  return (
    <div className="flex flex-col gap-4 py-1">
      <RuntimeCard />

      {data.pendingCount > 0 && (
        <div role="status" className="flex items-start gap-2.5 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-accent)] bg-[var(--lumi-accent-soft)] px-3.5 py-2.5">
          <AlertCircle aria-hidden className="mt-0.5 size-4 shrink-0 text-[var(--lumi-accent-text)]" />
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium text-[var(--lumi-text-primary)]">
              有 {data.pendingCount} 项设置需要重启 RSSHub 后生效
            </p>
            <p className="mt-0.5 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
              导出配置 → 应用到 RSSHub 容器环境 → 重启 → 点击「标记为已应用」。Lumi 不会自行重启 RSSHub。
            </p>
          </div>
        </div>
      )}

      {!data.configured && (
        <p className="text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
          服务端尚未配置 RSSHub 实例（RSSHUB_BASE_URL 为空），此处仅管理 desired 配置；来源发现预览将不可用。
        </p>
      )}

      {data.groups.map((group) => (
        <div key={group.id} className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-3.5 py-2">
          <p className="text-sm font-medium text-[var(--lumi-text-primary)]">{group.label}</p>
          <div className="divide-y divide-[var(--lumi-separator)]">
            {group.items.map((item) => (
              <ConfigField
                key={item.key}
                item={item}
                value={currentDraft[item.key] ?? item.default}
                onChange={(next) => setValue(item.key, next)}
              />
            ))}
          </div>
        </div>
      ))}

      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" onClick={save} disabled={Object.keys(dirtyEntries).length === 0 || patch.isPending}>
          {patch.isPending ? <Loader2 aria-hidden className="size-3.5 animate-spin" /> : <CheckCircle2 aria-hidden className="size-3.5" />}
          保存更改
        </Button>
        <Button
          size="sm"
          variant="secondary"
          onClick={() => { setError(null); setDraft(null) }}
          disabled={Object.keys(dirtyEntries).length === 0}
        >
          <RotateCcw aria-hidden className="size-3.5" />
          放弃更改
        </Button>
        <Button size="sm" variant="secondary" onClick={() => apply.mutate()} disabled={data.pendingCount === 0 || apply.isPending}>
          标记为已应用
        </Button>
        <a href="/api/v1/rsshub/config/export" download>
          <Button size="sm" variant="ghost">
            <Download aria-hidden className="size-3.5" />
            导出配置
          </Button>
        </a>
      </div>

      {error && (
        <p role="alert" className="text-xs leading-relaxed text-[var(--lumi-danger)]">
          保存失败：{error}
        </p>
      )}
      {(patch.isError || apply.isError) && (
        <p role="alert" className="text-xs leading-relaxed text-[var(--lumi-danger)]">
          操作失败，请稍后重试。
        </p>
      )}
    </div>
  )
}
