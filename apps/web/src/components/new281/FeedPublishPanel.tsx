/** NEW-285 个人简报 RSS 发布 — 可撤销私有订阅凭据（明文只展示一次）。 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import {
  enableFeed,
  fetchFeedState,
  revokeFeed,
  rotateFeed,
} from '../../api/new281'
import { NoteText, StatusLine, buttonClass, errorText, secondaryButtonClass } from './parts'

export function FeedPublishPanel() {
  const queryClient = useQueryClient()
  const [secret, setSecret] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const state = useQuery({
    queryKey: ['new281-feed-state'],
    queryFn: ({ signal }) => fetchFeedState(signal),
  })

  const invalidate = async () => {
    await queryClient.invalidateQueries({ queryKey: ['new281-feed-state'] })
  }

  const enableMutation = useMutation({
    mutationFn: enableFeed,
    onSuccess: async (created) => {
      setSecret(created.token)
      setNotice(created.note)
      await invalidate()
    },
    onError: (error) => setNotice(errorText(error)),
  })

  const rotateMutation = useMutation({
    mutationFn: rotateFeed,
    onSuccess: async (rotated) => {
      setSecret(rotated.token)
      setNotice(rotated.note)
      await invalidate()
    },
    onError: (error) => setNotice(errorText(error)),
  })

  const revokeMutation = useMutation({
    mutationFn: revokeFeed,
    onSuccess: async () => {
      setSecret(null)
      setNotice('feed 已撤销：所有订阅地址立即 404。')
      await invalidate()
    },
    onError: (error) => setNotice(errorText(error)),
  })

  return (
    <div className="flex flex-col gap-3">
      <NoteText>
        订阅地址 = 你的私有凭据（库中只存哈希；明文只在启用/轮换时显示这一次）。feed 只含<strong>已确认</strong>
        期次的摘要卡与更正提示，不含任何私人笔记；撤销后立即对全部订阅者 404。
      </NoteText>
      {state.isError && <StatusLine tone="error">{errorText(state.error)}</StatusLine>}
      {state.data && (
        <StatusLine tone="info" >
          {state.data.enabled
            ? `feed 启用中（创建于 ${state.data.createdAt}${state.data.rotatedAt ? `，轮换于 ${state.data.rotatedAt}` : ''}）。`
            : 'feed 未启用。'}
        </StatusLine>
      )}
      <div className="flex flex-wrap gap-2">
        <button type="button" className={buttonClass} disabled={enableMutation.isPending} onClick={() => enableMutation.mutate()}>
          启用订阅
        </button>
        {state.data?.enabled && (
          <>
            <button
              type="button"
              className={secondaryButtonClass}
              disabled={rotateMutation.isPending}
              onClick={() => rotateMutation.mutate()}
            >
              轮换 token
            </button>
            <button
              type="button"
              className={secondaryButtonClass}
              disabled={revokeMutation.isPending}
              onClick={() => revokeMutation.mutate()}
            >
              撤销订阅
            </button>
          </>
        )}
      </div>
      {secret && (
        <div
          data-new281-feed-secret=""
          className="break-all rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface-hover)] px-2 py-1.5 text-xs text-[var(--lumi-text-primary)]"
        >
          订阅地址（只显示这一次）：{secret.startsWith('/') ? '' : '/feeds/briefings/'}
          {secret.includes('/') ? secret : `${secret}.atom`}
        </div>
      )}
      {notice && <StatusLine tone={enableMutation.isError || rotateMutation.isError ? 'error' : 'ok'}>{notice}</StatusLine>}
    </div>
  )
}
