/** NEW-248 来源链接去追踪预览 — 复制前查看将移除的已知追踪参数；
 * 登录 / 内容选择必需参数与用户标记保留的参数绝不移除；可撤销保留标记。 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import {
  deleteKeptParam,
  listKeptParams,
  previewDetrack,
  putKeptParam,
  type DetrackPreview,
} from '../../api/new241'
import { Button } from '../ui/Button'
import { Skeleton } from '../ui/Skeleton'

export function DetrackPanel() {
  const queryClient = useQueryClient()
  const [url, setUrl] = useState('')
  const [preview, setPreview] = useState<DetrackPreview | null>(null)
  const [copied, setCopied] = useState(false)
  const [newParam, setNewParam] = useState('')
  const [newReason, setNewReason] = useState('')
  const [notice, setNotice] = useState<string | null>(null)

  const keptParams = useQuery({
    queryKey: ['new248-detrack-kept-params'],
    queryFn: ({ signal }) => listKeptParams(signal),
  })

  const invalidate = async () => {
    await queryClient.invalidateQueries({ queryKey: ['new248-detrack-kept-params'] })
  }

  const previewMutation = useMutation({
    mutationFn: () => previewDetrack(url),
    onSuccess: (result) => {
      setPreview(result)
      setCopied(false)
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : '预览失败'),
  })

  const copyMutation = useMutation({
    mutationFn: async () => {
      await navigator.clipboard.writeText(preview?.cleanedUrl ?? '')
    },
    onSuccess: () => setCopied(true),
    onError: (error) => setNotice(error instanceof Error ? error.message : '复制失败'),
  })

  const keepMutation = useMutation({
    mutationFn: () => putKeptParam(newParam, newReason),
    onSuccess: async () => {
      setNotice('已标记保留；之后的预览不会再移除该参数。')
      setNewParam('')
      setNewReason('')
      await invalidate()
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : '标记失败'),
  })

  const unkeepMutation = useMutation({
    mutationFn: (param: string) => deleteKeptParam(param),
    onSuccess: async () => {
      setNotice('已撤销保留；该参数恢复为可移除。')
      await invalidate()
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : '撤销失败'),
  })

  const keptItems = keptParams.data?.items ?? []

  return (
    <section
      aria-label="来源链接去追踪预览（NEW-248）"
      className="flex flex-col gap-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-3"
    >
      <div className="flex items-center gap-2">
        <h3 className="text-sm font-medium text-[var(--lumi-text-primary)]">来源链接去追踪预览</h3>
        <span className="text-xs text-[var(--lumi-text-tertiary)]">NEW-248</span>
      </div>

      <div className="flex gap-1">
        <input
          aria-label="来源链接地址"
          value={url}
          onChange={(event) => setUrl(event.target.value)}
          placeholder="粘贴要复制的链接"
          className="w-full rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-xs"
        />
        <Button
          size="sm"
          variant="secondary"
          disabled={url.trim() === '' || previewMutation.isPending}
          onClick={() => previewMutation.mutate()}
        >
          预览去追踪
        </Button>
      </div>

      {preview !== null && !preview.supported && (
        <p className="text-xs text-[var(--lumi-text-secondary)]">
          这个链接无法做去追踪预览。{preview.reason ?? ''}
        </p>
      )}
      {preview !== null && preview.supported && (
        <div className="flex flex-col gap-1 text-xs text-[var(--lumi-text-secondary)]" aria-label="去追踪预览结果">
          <span>将移除：{preview.removed.length > 0 ? preview.removed.join('、') : '（无已知追踪参数）'}</span>
          <span>
            保守保留（签名 / 登录 / 内容选择必需或清单外未知）：
            {preview.keptRequired.length > 0 ? preview.keptRequired.join('、') : '（无）'}
          </span>
          {preview.keptUser.length > 0 && <span>用户标记保留：{preview.keptUser.join('、')}</span>}
          <div className="flex gap-1">
            <input
              aria-label="去追踪后的链接"
              value={preview.cleanedUrl}
              readOnly
              className="w-full rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-xs"
            />
            <Button
              size="sm"
              variant="secondary"
              disabled={copyMutation.isPending}
              onClick={() => copyMutation.mutate()}
            >
              {copied ? '已复制' : '复制'}
            </Button>
          </div>
        </div>
      )}

      <div className="flex flex-col gap-1 border-t border-[var(--lumi-border)] pt-2">
        <p className="text-xs text-[var(--lumi-text-secondary)]">用户保留参数（预览永不移除；可撤销）</p>
        {keptParams.isPending && <Skeleton className="h-6 w-full" />}
        {keptParams.isError && (
          <div role="alert" className="text-xs text-[var(--lumi-text-secondary)]">
            保留清单加载失败。{keptParams.error instanceof Error ? keptParams.error.message : ''}
          </div>
        )}
        {keptItems.map((item) => (
          <div key={item.param} className="flex items-center gap-2 text-xs text-[var(--lumi-text-secondary)]">
            <span>
              {item.param}
              {item.reason !== '' ? `（${item.reason}）` : ''}
            </span>
            <Button
              size="sm"
              variant="secondary"
              disabled={unkeepMutation.isPending}
              onClick={() => unkeepMutation.mutate(item.param)}
            >
              撤销保留
            </Button>
          </div>
        ))}
        <div className="flex gap-1">
          <input
            aria-label="新保留参数名"
            value={newParam}
            onChange={(event) => setNewParam(event.target.value)}
            placeholder="参数名"
            className="w-full rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-xs"
          />
          <input
            aria-label="保留理由"
            value={newReason}
            onChange={(event) => setNewReason(event.target.value)}
            placeholder="保留理由（可空）"
            className="w-full rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-xs"
          />
          <Button
            size="sm"
            variant="secondary"
            disabled={newParam.trim() === '' || keepMutation.isPending}
            onClick={() => keepMutation.mutate()}
          >
            标记保留
          </Button>
        </div>
      </div>

      {notice !== null && (
        <p role="status" className="text-xs text-[var(--lumi-text-secondary)]">
          {notice}
        </p>
      )}
    </section>
  )
}
