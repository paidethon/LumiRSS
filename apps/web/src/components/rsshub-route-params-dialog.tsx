/** F047 RSSHub 路由参数编辑 —— 行菜单「路由参数」。
 *
 * 从 /api/v1/rsshub/routes 元数据匹配当前路由（pathTemplate 前缀匹配）：
 * - 命中 → 按参数定义（必填/枚举）生成表单，改参生成新地址预览；
 * - 未命中 → 退化为仅允许编辑 query 参数的通用表单。
 * token/key 类 query 值脱敏显示（***）；确认前用 feed-preview 预览新
 * 地址（失败不应用）；确认走 F044 迁移端点（旧源 replaced_by）。
 * N030：命中路由时可把当前参数组合「保存为方案」，并从「我的方案」
 * 一键回填——敏感参数值服务端只存 '***' 哨兵，回填后必须重新输入
 * （requiresRebind）才能预览；路径占位符参数不参与回填（本对话框
 * 不改路径段）。
 */

import { useMutation, useQuery } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { AlertCircle, CheckCircle2, RefreshCw, Save, Trash2 } from 'lucide-react'
import {
  applyRssHubParamPreset,
  getRssHubRoutes,
  migrateSubscription,
  previewFeed,
} from '../api/client'
import {
  useCreateRssHubParamPresetMutation,
  useDeleteRssHubParamPresetMutation,
  useRssHubParamPresets,
} from '../api/queries'
import type { RssHubParamPresetApply, RssHubParamPresetItem, Subscription } from '../api/types'
import { Button } from './ui/Button'
import { Dialog } from './ui/Dialog'
import { IconButton } from './ui/IconButton'
import { cx } from './ui/cx'
import {
  SENSITIVE_QUERY,
  maskQuery,
  matchRoute,
  extractPathParams,
  pathPlaceholderKeys,
} from '../lib/rsshub-params'

const inputCls =
  'w-full rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2.5 py-1.5 text-sm text-[var(--lumi-text-primary)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]'



interface RouteParamDef {
  name: string
  required: boolean
  type?: string | null
  enum?: string[] | null
  description?: string | null
}

export function RsshubRouteParamsDialog({
  open,
  onClose,
  subscription,
}: {
  open: boolean
  onClose: () => void
  subscription: Subscription
}) {
  const routesQuery = useQuery({
    queryKey: ['rsshub-routes'],
    queryFn: ({ signal }) => getRssHubRoutes(signal),
    enabled: open,
  })
  const feedUrl = subscription.feedUrl
  const [queryDraft, setQueryDraft] = useState<Record<string, string>>({})
  const [newQueryPairs, setNewQueryPairs] = useState<{ key: string; value: string }[]>([])
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  // N030：方案保存名 + 需重新绑定的敏感键（回填后必须重输才能预览）。
  const [presetName, setPresetName] = useState('')
  const [rebindKeys, setRebindKeys] = useState<string[]>([])
  const [presetNotice, setPresetNotice] = useState<string | null>(null)

  // 路由匹配：feedUrl 路径与 pathTemplate 前缀匹配（:param 段通配）
  const matchedRoute = useMemo(
    () => matchRoute(routesQuery.data?.routes ?? [], feedUrl),
    [routesQuery.data, feedUrl],
  )

  const paramDefs: RouteParamDef[] = useMemo(() => {
    const raw = (matchedRoute?.parameters ?? []) as {
      name?: string
      required?: boolean
      type?: string
      enum?: string[]
      description?: string
    }[]
    return raw
      .filter((param) => typeof param.name === 'string' && param.name !== '')
      .map((param) => ({
        name: param.name as string,
        required: param.required === true,
        type: param.type ?? null,
        enum: param.enum ?? null,
        description: param.description ?? null,
      }))
  }, [matchedRoute])

  // N030：当前路由模板下保存的方案（路径占位符不入表单，仅 query 生效）。
  const presetsQuery = useRssHubParamPresets(open && matchedRoute !== null)
  const createPresetMutation = useCreateRssHubParamPresetMutation()
  const deletePresetMutation = useDeleteRssHubParamPresetMutation()
  const applyPresetMutation = useMutation({
    mutationFn: (preset: RssHubParamPresetItem) => applyRssHubParamPreset(preset.id),
    onSuccess: (applied, preset) => applyPresetToForm(applied, preset.name),
  })

  const routePresets = useMemo(
    () =>
      (presetsQuery.data ?? []).filter(
        (preset) => matchedRoute !== null && preset.templateId === matchedRoute.id,
      ),
    [presetsQuery.data, matchedRoute],
  )

  // 新地址：现有 query + 修改后的 query 对 + 新增对（不改路径段——路径
  // 参数场景由 matchedRoute 分支用 pathOverrides 重建路径）。
  const builtUrl = useMemo(() => {
    try {
      const parts = new URL(feedUrl)
      for (const [key, value] of Object.entries(queryDraft)) {
        if (value === '') parts.searchParams.delete(key)
        else parts.searchParams.set(key, value)
      }
      for (const pair of newQueryPairs) {
        if (pair.key.trim() !== '') parts.searchParams.set(pair.key.trim(), pair.value)
      }
      return parts.toString()
    } catch {
      return feedUrl
    }
  }, [feedUrl, queryDraft, newQueryPairs])

  const existingQuery = useMemo(() => {
    try {
      return [...new URL(feedUrl).searchParams.entries()]
    } catch {
      return [] as [string, string][]
    }
  }, [feedUrl])

  // N030：预览被阻止——存在尚未重新输入的敏感键（哨兵永不外发）。
  const rebindPending = rebindKeys.some(
    (key) => (queryDraft[key] ?? '').trim() === '',
  )

  const previewMutation = useMutation({
    mutationFn: () => previewFeed(builtUrl),
    onSuccess: () => setPreviewUrl(builtUrl),
  })
  const applyMutation = useMutation({
    mutationFn: () => migrateSubscription(subscription.subscriptionRef, builtUrl),
    onSuccess: async () => {
      await previewMutation.reset()
      onClose()
    },
  })

  const reset = () => {
    setQueryDraft({})
    setNewQueryPairs([])
    setPreviewUrl(null)
    setRebindKeys([])
    setPresetNotice(null)
  }

  /** N030：把方案参数回填进表单（路径占位符跳过；敏感键进重新绑定）。 */
  function applyPresetToForm(applied: RssHubParamPresetApply, presetName: string) {
    const placeholders =
      matchedRoute !== null ? pathPlaceholderKeys(matchedRoute.pathTemplate) : []
    const draft: Record<string, string> = {}
    const sensitive: string[] = []
    for (const [key, value] of Object.entries(applied.params)) {
      if (placeholders.includes(key)) continue // 本对话框不改路径段
      if (value === '' || value === '***' || SENSITIVE_QUERY.test(key)) {
        if (value !== '') sensitive.push(key)
        continue
      }
      draft[key] = value
    }
    setQueryDraft((prev) => ({ ...prev, ...draft }))
    setNewQueryPairs([])
    setPreviewUrl(null)
    setRebindKeys(sensitive)
    setPresetNotice(
      sensitive.length > 0
        ? `已回填「${presetName}」。敏感参数需重新输入：${sensitive.join('、')}`
        : `已回填「${presetName}」。`,
    )
  }

  /** N030：当前参数组合（模板路径参数 + 新地址 query）→ 保存为方案。 */
  function currentPresetParams(): Record<string, string> | null {
    if (matchedRoute === null) return null
    const pathParams = extractPathParams(matchedRoute.pathTemplate, feedUrl)
    if (pathParams === null) return null
    let queryPairs: [string, string][] = []
    try {
      queryPairs = [...new URL(builtUrl).searchParams.entries()]
    } catch {
      return null
    }
    return { ...pathParams, ...Object.fromEntries(queryPairs) }
  }

  function savePreset() {
    const params = currentPresetParams()
    if (matchedRoute === null || params === null || presetName.trim() === '') return
    createPresetMutation.mutate(
      { routeId: matchedRoute.id, params, name: presetName.trim() },
      {
        onSuccess: (preset) => {
          setPresetName('')
          setPresetNotice(`已保存方案「${preset.name}」。`)
        },
      },
    )
  }

  return (
    <Dialog open={open} onClose={onClose} title={`路由参数 — ${subscription.title}`}>
      <div className="flex flex-col gap-3">
        {routesQuery.isPending && <p className="text-xs text-[var(--lumi-text-tertiary)]">加载路由元数据…</p>}
        {routesQuery.isSuccess && matchedRoute === null && (
          <p className="text-xs leading-relaxed text-[var(--lumi-text-tertiary)]">
            该地址未匹配到已知路由元数据——退化为通用 query 参数编辑。
          </p>
        )}
        {matchedRoute !== null && (
          <div className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-2.5 text-xs">
            <p className="font-medium text-[var(--lumi-text-primary)]">{matchedRoute.title}</p>
            <p className="mt-0.5 text-[var(--lumi-text-tertiary)]">{matchedRoute.pathTemplate}</p>
          </div>
        )}

        {/* query 参数编辑（通用 + 路由元数据声明的 query 参数） */}
        {existingQuery.length > 0 && (
          <div className="flex flex-col gap-1.5">
            <p className="text-xs font-medium text-[var(--lumi-text-primary)]">现有参数</p>
            {existingQuery.map(([key, value]) => (
              <label key={key} className="flex items-center gap-2 text-xs text-[var(--lumi-text-secondary)]">
                <span className="w-28 shrink-0 truncate font-mono">{key}</span>
                {SENSITIVE_QUERY.test(key) ? (
                  <input className={inputCls} aria-label={`参数 ${key}`} value="***" readOnly />
                ) : (
                  <input
                    className={inputCls}
                    aria-label={`参数 ${key}`}
                    value={queryDraft[key] ?? value}
                    onChange={(e) => setQueryDraft((prev) => ({ ...prev, [key]: e.target.value }))}
                  />
                )}
              </label>
            ))}
          </div>
        )}

        {matchedRoute !== null && paramDefs.length > 0 && (
          <div className="flex flex-col gap-1.5">
            <p className="text-xs font-medium text-[var(--lumi-text-primary)]">路由参数</p>
            {paramDefs.map((param) => (
              <label key={param.name} className="flex items-center gap-2 text-xs text-[var(--lumi-text-secondary)]">
                <span className="w-28 shrink-0 truncate font-mono">
                  {param.name}
                  {param.required && <span className="text-[var(--lumi-danger)]"> *</span>}
                </span>
                {param.enum !== null && param.enum !== undefined && param.enum.length > 0 ? (
                  <select
                    aria-label={`路由参数 ${param.name}`}
                    className={cx(inputCls, 'flex-1')}
                    value={queryDraft[param.name] ?? ''}
                    onChange={(e) => setQueryDraft((prev) => ({ ...prev, [param.name]: e.target.value }))}
                  >
                    <option value="">（不变）</option>
                    {param.enum.map((option) => (
                      <option key={option} value={option}>{option}</option>
                    ))}
                  </select>
                ) : (
                  <input
                    className={inputCls}
                    aria-label={`路由参数 ${param.name}`}
                    value={queryDraft[param.name] ?? ''}
                    onChange={(e) => setQueryDraft((prev) => ({ ...prev, [param.name]: e.target.value }))}
                  />
                )}
              </label>
            ))}
          </div>
        )}

        {newQueryPairs.map((pair, index) => (
          <div key={index} className="flex items-center gap-2">
            <input
              aria-label="新参数名"
              placeholder="参数名"
              className={cx(inputCls, 'w-28')}
              value={pair.key}
              onChange={(e) =>
                setNewQueryPairs((prev) => prev.map((p, i) => (i === index ? { ...p, key: e.target.value } : p)))
              }
            />
            <input
              aria-label="新参数值"
              placeholder="值"
              className={cx(inputCls, 'flex-1')}
              value={pair.value}
              onChange={(e) =>
                setNewQueryPairs((prev) => prev.map((p, i) => (i === index ? { ...p, value: e.target.value } : p)))
              }
            />
          </div>
        ))}
        <Button size="sm" variant="ghost" onClick={() => setNewQueryPairs((prev) => [...prev, { key: '', value: '' }])}>
          添加参数
        </Button>

        {/* N030：需重新绑定的敏感键（方案回填后必须重输，哨兵永不外发） */}
        {rebindKeys.map((key) => (
          <label key={key} className="flex items-center gap-2 text-xs text-[var(--lumi-text-secondary)]">
            <span className="w-28 shrink-0 truncate font-mono">{key}</span>
            <input
              className={cx(inputCls, 'flex-1 border-[var(--lumi-accent)]')}
              aria-label={`重新输入 ${key}`}
              autoComplete="off"
              placeholder="敏感参数不保存，需重新输入"
              value={queryDraft[key] ?? ''}
              onChange={(e) => {
                setQueryDraft((prev) => ({ ...prev, [key]: e.target.value }))
                setPresetNotice(null)
              }}
            />
          </label>
        ))}
        {rebindPending && (
          <p role="alert" className="flex items-start gap-1.5 text-xs text-[var(--lumi-danger)]">
            <AlertCircle aria-hidden className="mt-0.5 size-3.5 shrink-0" />
            敏感参数未保存原值——重新输入后才能预览。
          </p>
        )}

        {/* N030：我的方案（仅当前路由模板；点击回填，垃圾桶删除） */}
        {matchedRoute !== null && (
          <section aria-label="我的方案" className="flex flex-col gap-1.5 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-2.5">
            <p className="text-xs font-medium text-[var(--lumi-text-primary)]">我的方案</p>
            {presetsQuery.isPending && (
              <p className="text-xs text-[var(--lumi-text-tertiary)]">加载方案…</p>
            )}
            {presetsQuery.isError && (
              <p role="alert" className="text-xs text-[var(--lumi-danger)]">
                方案加载失败。
                <button
                  type="button"
                  className="ml-1 underline"
                  onClick={() => presetsQuery.refetch()}
                >
                  重试
                </button>
              </p>
            )}
            {presetsQuery.isSuccess && routePresets.length === 0 && (
              <p className="text-xs text-[var(--lumi-text-tertiary)]">该路由暂无保存的方案。</p>
            )}
            {routePresets.map((preset) => {
              const summary = Object.entries(preset.params)
                .map(([key, value]) => `${key}=${value}`)
                .join('  ')
              return (
                <div key={preset.id} className="flex min-h-9 items-center gap-2">
                  <button
                    type="button"
                    disabled={applyPresetMutation.isPending}
                    onClick={() => {
                      setPresetNotice(null)
                      applyPresetMutation.mutate(preset)
                    }}
                    className={cx(
                      'min-w-0 flex-1 rounded-[var(--lumi-radius-sm)] px-2 py-1.5 text-left',
                      'transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)]',
                      'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
                    )}
                  >
                    <span className="block truncate text-xs text-[var(--lumi-text-primary)]">
                      {preset.name}
                      {preset.hasSensitive && (
                        <span className="ml-1.5 text-[11px] text-[var(--lumi-text-tertiary)]">
                          需重新绑定
                        </span>
                      )}
                    </span>
                    {summary !== '' && (
                      <span className="block truncate font-mono text-[11px] text-[var(--lumi-text-tertiary)]">
                        {summary}
                      </span>
                    )}
                  </button>
                  <IconButton
                    icon={<Trash2 aria-hidden className="size-3.5" />}
                    label={`删除方案 ${preset.name}`}
                    size="sm"
                    disabled={deletePresetMutation.isPending}
                    onClick={() => deletePresetMutation.mutate(preset.id)}
                  />
                </div>
              )
            })}
            <div className="flex items-center gap-2 border-t border-[var(--lumi-border)] pt-2">
              <input
                className={cx(inputCls, 'flex-1')}
                aria-label="方案名称"
                placeholder="方案名称"
                value={presetName}
                maxLength={80}
                onChange={(e) => setPresetName(e.target.value)}
              />
              <Button
                size="sm"
                variant="secondary"
                disabled={
                  presetName.trim() === '' ||
                  currentPresetParams() === null ||
                  createPresetMutation.isPending
                }
                onClick={savePreset}
              >
                <Save aria-hidden className="size-3.5" />
                {createPresetMutation.isPending ? '保存中…' : '保存为方案'}
              </Button>
            </div>
            {createPresetMutation.isError && (
              <p role="alert" className="text-xs text-[var(--lumi-danger)]">
                {createPresetMutation.error instanceof Error
                  ? createPresetMutation.error.message
                  : '方案保存失败'}
              </p>
            )}
          </section>
        )}
        {presetNotice !== null && (
          <p role="status" className="text-xs text-[var(--lumi-text-secondary)]">
            {presetNotice}
          </p>
        )}

        <div className="rounded-[var(--lumi-radius-md)] bg-[var(--lumi-surface-hover)] p-2.5 text-xs">
          <p className="text-[var(--lumi-text-tertiary)]">新地址预览（敏感参数已脱敏）</p>
          <p className="mt-0.5 break-all font-mono text-[var(--lumi-text-primary)]">{maskQuery(builtUrl)}</p>
        </div>

        {previewMutation.isError && (
          <p role="alert" className="flex items-start gap-1.5 text-xs text-[var(--lumi-danger)]">
            <AlertCircle aria-hidden className="mt-0.5 size-3.5 shrink-0" />
            预览失败（地址不可达或非法）：{previewMutation.error instanceof Error ? previewMutation.error.message : '请检查参数'}
          </p>
        )}
        {previewUrl !== null && (
          <p className="flex items-center gap-1.5 text-xs text-[var(--lumi-text-secondary)]">
            <CheckCircle2 aria-hidden className="size-3.5" /> 预览通过——确认后将新建订阅并保留旧订阅（可自行退订）。
          </p>
        )}
        {applyMutation.isError && (
          <p role="alert" className="text-xs text-[var(--lumi-danger)]">
            {applyMutation.error instanceof Error ? applyMutation.error.message : '应用失败'}
          </p>
        )}
        <div className="flex items-center justify-end gap-2">
          <Button size="sm" variant="ghost" onClick={reset}>重置</Button>
          <Button
            size="sm"
            variant="secondary"
            disabled={previewMutation.isPending || rebindPending}
            onClick={() => previewMutation.mutate()}
          >
            <RefreshCw aria-hidden className="size-3.5" />
            {previewMutation.isPending ? '预览中…' : '预览'}
          </Button>
          <Button
            size="sm"
            variant="primary"
            disabled={previewUrl === null || applyMutation.isPending}
            onClick={() => applyMutation.mutate()}
          >
            {applyMutation.isPending ? '应用中…' : '应用'}
          </Button>
        </div>
      </div>
    </Dialog>
  )
}
