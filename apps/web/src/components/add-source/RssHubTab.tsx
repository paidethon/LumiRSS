/** RssHubTab — 添加来源 · RSSHub 模式（0014）。
 *
 * 用户闭环：GET /api/v1/rsshub/routes（Lumi 静态精选目录）→ 搜索/选择
 * 路由 → 参数表单（required/optional、示例、本地格式校验）→
 * POST /api/v1/rsshub/preview（BFF 构造路径并抓取，浏览器不直连 RSSHub）
 * → 共享 PreviewStage（分类 + 订阅）。
 *
 * N021：目录上方有 收藏 / 最近使用 两个服务端持久化区块（跨设备）；
 * 目录行内 ★ 切换收藏；点收藏/最近条目回填路由与参数（敏感参数值在
 * 服务端只存 '***' 哨兵，回填的哨兵值再预览会被服务端 pattern 拒绝，
 * 需重填——这是有意的安全行为）。
 *
 * 安全边界：路径构造与实例抓取全部在 BFF（服务端配置的 RSSHUB_BASE_URL）；
 * 前端只提交参数值，pattern 校验仅是即时反馈，真正的校验在服务端。 */

import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { AlertCircle, History, Loader2, Satellite, Search, Star } from 'lucide-react'
import {
  useDeleteRssHubFavoriteMutation,
  usePutRssHubFavoriteMutation,
  useRssHubFavorites,
  useRssHubPreviewMutation,
  useRssHubRecent,
  useRssHubRoutes,
  useSubscribeMutation,
} from '../../api/queries'
import type {
  FeedPreviewMetadata,
  RssHubRoute,
} from '../../api/types'
import { formatRelativeTime } from '../../lib/date-format'
import { managementErrorText } from '../../lib/management-errors'
import { Button } from '../ui/Button'
import { EmptyState } from '../ui/EmptyState'
import { IconButton } from '../ui/IconButton'
import { Skeleton } from '../ui/Skeleton'
import { cx } from '../ui/cx'
import { PreviewStage } from './PreviewStage'
import type { AddSourceTabProps } from './DirectFeedTab'

export function RssHubTab({ onClose, registerGuard }: AddSourceTabProps) {
  const queryClient = useQueryClient()
  const routesQuery = useRssHubRoutes(true)
  const previewMutation = useRssHubPreviewMutation()
  const subscribeMutation = useSubscribeMutation()
  const favoritesQuery = useRssHubFavorites(true)
  const recentQuery = useRssHubRecent(true)
  const putFavoriteMutation = usePutRssHubFavoriteMutation()
  const deleteFavoriteMutation = useDeleteRssHubFavoriteMutation()

  const [query, setQuery] = useState('')
  const [selectedRouteId, setSelectedRouteId] = useState<string | null>(null)
  const [paramValues, setParamValues] = useState<Record<string, string>>({})
  const [localParamError, setLocalParamError] = useState<string | null>(null)
  const [preview, setPreview] = useState<FeedPreviewMetadata | null>(null)
  const [subscribed, setSubscribed] = useState(false)

  const busy =
    previewMutation.isPending || subscribeMutation.isPending || subscribed
  // 关闭防护只挡 pending（成功后允许 Escape / 完成关闭）
  const pending = previewMutation.isPending || subscribeMutation.isPending

  useEffect(() => {
    registerGuard(() => !pending)
    return () => registerGuard(null)
  }, [pending, registerGuard])

  const routesData = routesQuery.data
  const routes = useMemo(() => routesData?.routes ?? [], [routesData])
  const configured = routesData?.configured ?? false

  const filteredRoutes = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return routes
    return routes.filter(
      (route) =>
        route.title.toLowerCase().includes(q) ||
        route.description.toLowerCase().includes(q),
    )
  }, [routes, query])

  const selectedRoute: RssHubRoute | null =
    routes.find((route) => route.id === selectedRouteId) ?? null

  // N021：收藏（目录级 = 无参数收藏）与最近使用；条目回填路由与参数。
  const favorites = useMemo(
    () => favoritesQuery.data ?? [],
    [favoritesQuery.data],
  )
  const recent = useMemo(() => recentQuery.data ?? [], [recentQuery.data])
  const favoritePending =
    putFavoriteMutation.isPending || deleteFavoriteMutation.isPending

  function toggleFavorite(route: RssHubRoute) {
    const existing = favorites.find(
      (favorite) =>
        favorite.templateId === route.id && Object.keys(favorite.params).length === 0,
    )
    if (existing !== undefined) {
      deleteFavoriteMutation.mutate(existing.routeKey)
    } else {
      putFavoriteMutation.mutate({ routeId: route.id, params: {}, label: route.title })
    }
  }

  function openEntry(entry: { templateId: string; params: Record<string, string> }) {
    const route = routes.find((candidate) => candidate.id === entry.templateId)
    if (route === undefined) return
    setSelectedRouteId(route.id)
    setParamValues({ ...entry.params })
    setLocalParamError(null)
    setPreview(null)
    previewMutation.reset()
  }

  function selectRoute(route: RssHubRoute) {
    setSelectedRouteId(route.id)
    setParamValues({})
    setLocalParamError(null)
    setPreview(null)
    previewMutation.reset()
  }

  function backToRoutes() {
    setSelectedRouteId(null)
    setParamValues({})
    setLocalParamError(null)
    setPreview(null)
    previewMutation.reset()
  }

  function startPreview() {
    if (selectedRoute === null) return
    const values: Record<string, string> = {}
    for (const parameter of selectedRoute.parameters) {
      const value = (paramValues[parameter.key] ?? '').trim()
      if (parameter.required && !value) {
        setLocalParamError(`请填写「${parameter.label}」。`)
        return
      }
      if (value && !new RegExp(`^(?:${parameter.pattern})$`).test(value)) {
        setLocalParamError(`「${parameter.label}」格式不正确（示例：${parameter.example}）。`)
        return
      }
      values[parameter.key] = value
    }
    setLocalParamError(null)
    setPreview(null)
    previewMutation.mutate(
      { routeId: selectedRoute.id, params: values },
      {
        onSuccess: (metadata) => {
          setPreview(metadata)
          // N021：成功 preview 已在服务端 upsert 最近使用——拉新列表
          void queryClient.invalidateQueries({ queryKey: ['rsshub-recent'] })
        },
      },
    )
  }

  const allParamsFilled = selectedRoute?.parameters.every(
    (parameter) =>
      !parameter.required || (paramValues[parameter.key] ?? '').trim() !== '',
  ) ?? false

  return (
    <div className="flex flex-col gap-4">
      {/* 路由目录 loading / 错误 / 未配置 */}
      {preview === null && selectedRoute === null && (
        <>
          {routesQuery.isPending && (
            <div className="flex flex-col gap-2" aria-label="正在加载 RSSHub 路由">
              <Skeleton className="h-5 w-1/2" />
              <Skeleton className="h-14 w-full" />
              <Skeleton className="h-14 w-full" />
              <Skeleton className="h-14 w-full" />
            </div>
          )}

          {routesQuery.isError && !routesQuery.isPending && (
            <div className="flex flex-col gap-2" role="alert">
              <div
                className="flex items-start gap-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-danger)]/30 bg-[var(--lumi-danger)]/10 px-3 py-2.5 text-sm text-[var(--lumi-danger)]"
              >
                <AlertCircle aria-hidden className="mt-0.5 size-4 shrink-0" />
                {managementErrorText(routesQuery.error).title}
              </div>
              <div className="flex justify-end">
                <Button size="sm" onClick={() => routesQuery.refetch()}>
                  重试
                </Button>
              </div>
            </div>
          )}

          {!routesQuery.isPending && !routesQuery.isError && !configured && (
            <div
              role="status"
              className="flex items-start gap-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-3 py-2.5 text-sm text-[var(--lumi-text-secondary)]"
            >
              <Satellite aria-hidden className="mt-0.5 size-4 shrink-0 text-[var(--lumi-text-tertiary)]" />
              <span className="min-w-0">
                <span className="block font-medium text-[var(--lumi-text-primary)]">
                  RSSHub 未配置
                </span>
                <span className="mt-0.5 block text-xs">
                  服务端未设置 RSSHub 实例，暂无法使用 RSSHub 来源。网站来源仍可正常使用。
                </span>
              </span>
            </div>
          )}

          {configured && !routesQuery.isPending && !routesQuery.isError && (
            <>
              {/* N021：收藏 / 最近使用（服务端持久化；空则不渲染区块） */}
              {favorites.length > 0 && (
                <RouteEntrySection
                  title="收藏"
                  entries={favorites.map((favorite) => ({
                    key: favorite.routeKey,
                    templateId: favorite.templateId,
                    params: favorite.params,
                    meta: favorite.label || undefined,
                  }))}
                  routes={routes}
                  icon={<Star aria-hidden className="size-3.5 fill-current" />}
                  onOpen={openEntry}
                />
              )}
              {recent.length > 0 && (
                <RouteEntrySection
                  title="最近使用"
                  entries={recent.map((item) => ({
                    key: item.routeKey,
                    templateId: item.templateId,
                    params: item.params,
                    meta: formatRelativeTime(item.lastUsedAt),
                  }))}
                  routes={routes}
                  icon={<History aria-hidden className="size-3.5" />}
                  onOpen={openEntry}
                />
              )}

              {/* 本地搜索（14 条精选路由；客户端过滤，文案诚实） */}
              <div className="relative">
                <Search
                  aria-hidden
                  className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-[var(--lumi-text-tertiary)]"
                />
                <input
                  type="search"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="搜索 RSSHub 路由"
                  aria-label="搜索 RSSHub 路由"
                  className={cx(
                    'w-full rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)]',
                    'py-2.5 pl-9 pr-3 text-sm text-[var(--lumi-text-primary)]',
                    'placeholder:text-[var(--lumi-text-tertiary)]',
                    'focus:outline-2 focus:-outline-offset-2 focus:outline-[var(--lumi-focus-ring)]',
                  )}
                />
              </div>

              {filteredRoutes.length === 0 ? (
                <EmptyState
                  icon={<Search aria-hidden className="size-6" />}
                  title="没有匹配的 RSSHub 路由"
                  description="换个关键词试试。"
                />
              ) : (
                <div
                  role="radiogroup"
                  aria-label="RSSHub 路由"
                  className="flex max-h-64 flex-col gap-2 overflow-y-auto pr-1"
                >
                  {filteredRoutes.map((route) => {
                    const favorited = favorites.some(
                      (favorite) =>
                        favorite.templateId === route.id &&
                        Object.keys(favorite.params).length === 0,
                    )
                    return (
                      <div
                        key={route.id}
                        className={cx(
                          'flex min-h-14 items-center gap-1 rounded-[var(--lumi-radius-md)] border px-3.5 py-2.5',
                          'transition-colors duration-[var(--lumi-motion-fast)]',
                          route.id === selectedRouteId
                            ? 'border-[var(--lumi-accent)] bg-[var(--lumi-surface-selected)]'
                            : 'border-[var(--lumi-border)] bg-[var(--lumi-surface)] hover:bg-[var(--lumi-surface-hover)]',
                        )}
                      >
                        <label className="flex min-w-0 flex-1 cursor-pointer items-center gap-3">
                          <input
                            type="radio"
                            name="add-source-rsshub-route"
                            value={route.id}
                            checked={route.id === selectedRouteId}
                            onChange={() => selectRoute(route)}
                            className="sr-only"
                          />
                          <span className="min-w-0 flex-1">
                            <span className="block truncate text-sm text-[var(--lumi-text-primary)]">
                              {route.title}
                            </span>
                            <span className="block truncate text-xs text-[var(--lumi-text-tertiary)]">
                              {route.description}
                            </span>
                            <span className="mt-0.5 block truncate font-mono text-[11px] text-[var(--lumi-text-tertiary)]">
                              {route.pathTemplate}
                            </span>
                          </span>
                        </label>
                        <IconButton
                          icon={
                            <Star
                              aria-hidden
                              className={cx(
                                'size-4',
                                favorited && 'fill-[var(--lumi-accent)] text-[var(--lumi-accent)]',
                              )}
                            />
                          }
                          label={favorited ? `取消收藏 ${route.title}` : `收藏 ${route.title}`}
                          size="sm"
                          touch
                          disabled={favoritePending}
                          onClick={() => toggleFavorite(route)}
                        />
                      </div>
                    )
                  })}
                </div>
              )}
            </>
          )}
        </>
      )}

      {/* 参数表单（选中路由后） */}
      {selectedRoute !== null && preview === null && (
        <div className="flex flex-col gap-3">
          <div>
            <p className="text-sm font-semibold text-[var(--lumi-text-primary)]">
              {selectedRoute.title}
            </p>
            <p className="mt-0.5 font-mono text-[11px] text-[var(--lumi-text-tertiary)]">
              {selectedRoute.pathTemplate}
            </p>
          </div>

          {selectedRoute.parameters.map((parameter) => (
            <div key={parameter.key} className="flex flex-col gap-1.5">
              <label
                htmlFor={`add-source-rsshub-param-${parameter.key}`}
                className="text-sm font-medium text-[var(--lumi-text-primary)]"
              >
                {parameter.label}
                {parameter.required && (
                  <span aria-hidden className="ml-1 text-[var(--lumi-danger)]">
                    *
                  </span>
                )}
              </label>
              <input
                id={`add-source-rsshub-param-${parameter.key}`}
                type="text"
                autoComplete="off"
                spellCheck={false}
                value={paramValues[parameter.key] ?? ''}
                onChange={(e) => {
                  setParamValues((prev) => ({ ...prev, [parameter.key]: e.target.value }))
                  setLocalParamError(null)
                }}
                placeholder={parameter.example}
                aria-describedby={`add-source-rsshub-param-${parameter.key}-help`}
                className={cx(
                  'min-h-11 w-full rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)]',
                  'bg-[var(--lumi-surface)] px-3 py-2.5 text-sm text-[var(--lumi-text-primary)]',
                  'placeholder:text-[var(--lumi-text-tertiary)]',
                  'focus:outline-2 focus:-outline-offset-2 focus:outline-[var(--lumi-focus-ring)]',
                )}
              />
              <p
                id={`add-source-rsshub-param-${parameter.key}-help`}
                className="text-xs text-[var(--lumi-text-tertiary)]"
              >
                {parameter.help}
              </p>
            </div>
          ))}

          {localParamError !== null && (
            <p role="alert" className="text-xs text-[var(--lumi-danger)]">
              {localParamError}
            </p>
          )}

          {/* 预览 loading */}
          {previewMutation.isPending && (
            <div className="flex flex-col gap-2" aria-label="正在获取订阅源信息">
              <Skeleton className="h-5 w-2/3" />
              <Skeleton className="h-4 w-1/2" />
              <Skeleton className="h-4 w-full" />
            </div>
          )}

          {/* 预览错误 */}
          {previewMutation.error !== null && !previewMutation.isPending && (
            <div
              role="alert"
              className="flex items-start gap-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-danger)]/30 bg-[var(--lumi-danger)]/10 px-3 py-2.5 text-sm text-[var(--lumi-danger)]"
            >
              <AlertCircle aria-hidden className="mt-0.5 size-4 shrink-0" />
              <span className="min-w-0">
                <span className="block font-medium">
                  {managementErrorText(previewMutation.error).title}
                </span>
                {managementErrorText(previewMutation.error).detail !== null && (
                  <span className="mt-0.5 block text-xs opacity-80">
                    {managementErrorText(previewMutation.error).detail}
                  </span>
                )}
              </span>
            </div>
          )}
        </div>
      )}

      {/* 预览成功：共享 预览 → 分类 → 订阅 阶段 */}
      {preview !== null && (
        <PreviewStage
          preview={preview}
          subscribeMutation={subscribeMutation}
          subscribed={subscribed}
          onSubscribed={() => setSubscribed(true)}
          onBack={backToRoutes}
        />
      )}

      {/* 底部操作区 */}
      <div className="mt-1 flex justify-end gap-2">
        {!subscribed && (
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            取消
          </Button>
        )}
        {subscribed ? (
          <Button variant="primary" onClick={onClose}>
            完成
          </Button>
        ) : preview !== null ? null : selectedRoute === null ? null : (
          <Button
            variant="primary"
            onClick={startPreview}
            disabled={busy || !allParamsFilled}
          >
            {previewMutation.isPending ? (
              <>
                <Loader2 aria-hidden className="size-4 animate-spin" />
                预览中…
              </>
            ) : (
              '预览'
            )}
          </Button>
        )}
      </div>
    </div>
  )
}

interface RouteEntry {
  key: string
  templateId: string
  params: Record<string, string>
  meta?: string
}

/** N021：收藏 / 最近使用区块 — 模板标题 + 脱敏参数摘要 + 元信息。 */
function RouteEntrySection({
  title,
  entries,
  routes,
  icon,
  onOpen,
}: {
  title: string
  entries: RouteEntry[]
  routes: RssHubRoute[]
  icon: ReactNode
  onOpen: (entry: RouteEntry) => void
}) {
  return (
    <section aria-label={title} className="flex flex-col gap-1.5">
      <p className="text-xs font-medium text-[var(--lumi-text-secondary)]">{title}</p>
      {entries.map((entry) => {
        const route = routes.find((candidate) => candidate.id === entry.templateId)
        const paramSummary = Object.entries(entry.params)
          .map(([key, value]) => `${key}=${value}`)
          .join('  ')
        return (
          <button
            key={entry.key}
            type="button"
            onClick={() => onOpen(entry)}
            className={cx(
              'flex min-h-11 items-center gap-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)]',
              'bg-[var(--lumi-surface)] px-3 py-2 text-left',
              'transition-colors duration-[var(--lumi-motion-fast)]',
              'hover:bg-[var(--lumi-surface-hover)]',
              'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
            )}
          >
            <span aria-hidden className="text-[var(--lumi-text-tertiary)]">
              {icon}
            </span>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm text-[var(--lumi-text-primary)]">
                {route?.title ?? entry.templateId}
              </span>
              <span className="block truncate font-mono text-[11px] text-[var(--lumi-text-tertiary)]">
                {paramSummary || route?.pathTemplate || entry.templateId}
              </span>
            </span>
            {entry.meta !== undefined && entry.meta !== '' && (
              <span className="shrink-0 text-[11px] text-[var(--lumi-text-tertiary)]">
                {entry.meta}
              </span>
            )}
          </button>
        )
      })}
    </section>
  )
}
