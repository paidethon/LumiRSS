/** RssHubTab — 添加来源 · RSSHub 模式（0014）。
 *
 * 用户闭环：GET /api/v1/rsshub/routes（Lumi 静态精选目录）→ 搜索/选择
 * 路由 → 参数表单（required/optional、示例、本地格式校验）→
 * POST /api/v1/rsshub/preview（BFF 构造路径并抓取，浏览器不直连 RSSHub）
 * → 共享 PreviewStage（分类 + 订阅）。
 *
 * 安全边界：路径构造与实例抓取全部在 BFF（服务端配置的 RSSHUB_BASE_URL）；
 * 前端只提交参数值，pattern 校验仅是即时反馈，真正的校验在服务端。 */

import { useEffect, useMemo, useState } from 'react'
import { AlertCircle, Loader2, Satellite, Search } from 'lucide-react'
import {
  useRssHubPreviewMutation,
  useRssHubRoutes,
  useSubscribeMutation,
} from '../../api/queries'
import type { FeedPreviewMetadata, RssHubRoute } from '../../api/types'
import { managementErrorText } from '../../lib/management-errors'
import { Button } from '../ui/Button'
import { EmptyState } from '../ui/EmptyState'
import { Skeleton } from '../ui/Skeleton'
import { cx } from '../ui/cx'
import { PreviewStage } from './PreviewStage'
import type { AddSourceTabProps } from './DirectFeedTab'

export function RssHubTab({ onClose, registerGuard }: AddSourceTabProps) {
  const routesQuery = useRssHubRoutes(true)
  const previewMutation = useRssHubPreviewMutation()
  const subscribeMutation = useSubscribeMutation()

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
      { onSuccess: (metadata) => setPreview(metadata) },
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
                  {filteredRoutes.map((route) => (
                    <label
                      key={route.id}
                      className={cx(
                        'flex min-h-14 cursor-pointer items-center gap-3 rounded-[var(--lumi-radius-md)] border px-3.5 py-2.5',
                        'transition-colors duration-[var(--lumi-motion-fast)]',
                        route.id === selectedRouteId
                          ? 'border-[var(--lumi-accent)] bg-[var(--lumi-surface-selected)]'
                          : 'border-[var(--lumi-border)] bg-[var(--lumi-surface)] hover:bg-[var(--lumi-surface-hover)]',
                      )}
                    >
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
                  ))}
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
