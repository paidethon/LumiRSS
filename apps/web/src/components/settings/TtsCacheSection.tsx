/** TtsCacheSection — N098 音频生成缓存管理（设置 → 数据控制）。
 *
 * 服务端 TTS 缓存清单（size/date）+ 单条删除 + 一键清空（全部只作用于
 * 本人 —— per-user 库）。诚实口径：缓存/合成只在用户配置了 TTS 能力的
 * AI provider（purpose=tts）后可用；未配置时列表请求失败如实提示，
 * 绝不假装可合成。
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Trash2 } from 'lucide-react'
import { clearTtsCache, deleteTtsCache, listTtsCache } from '../../api/client'
import { Button } from '../ui/Button'
import { EmptyState } from '../ui/EmptyState'
import { Skeleton } from '../ui/Skeleton'

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export function TtsCacheSection() {
  const queryClient = useQueryClient()
  const [notice, setNotice] = useState<string | null>(null)
  const cacheQuery = useQuery({
    queryKey: ['tts-cache'],
    queryFn: ({ signal }) => listTtsCache(signal),
    retry: false,
  })

  const invalidate = async () => {
    await queryClient.invalidateQueries({ queryKey: ['tts-cache'] })
  }
  const removeOne = useMutation({
    mutationFn: (id: string) => deleteTtsCache(id),
    onSuccess: () => void invalidate(),
  })
  const clearAll = useMutation({
    mutationFn: () => clearTtsCache(),
    onSuccess: (result) => {
      setNotice(`已清空 ${result.removed} 条缓存。`)
      return invalidate()
    },
  })

  const body = cacheQuery.data

  return (
    <section
      aria-label="音频生成缓存"
      data-testid="tts-cache-section"
      className="flex flex-col gap-2"
    >
      <p className="text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
        服务端语音合成（TTS）的缓存管理。只在「AI」设置为 TTS 用途配置了
        OpenAI 兼容 provider 后可用；缓存上限 50MB（超出按最旧先删）。
      </p>
      {cacheQuery.isPending && <Skeleton className="h-12 w-full" />}
      {cacheQuery.isError && (
        <p role="alert" className="text-xs text-[var(--lumi-text-tertiary)]">
          缓存清单不可用（服务端可能尚未启用 TTS 缓存，或未配置 TTS provider）。
        </p>
      )}
      {cacheQuery.isSuccess && body !== undefined && (
        <>
          {body.count === 0 ? (
            <EmptyState
              title="缓存为空"
              description="在阅读页发起服务端语音合成后，生成的音频会缓存在这里（同文本零重复调用）。"
            />
          ) : (
            <ul className="flex flex-col gap-1.5">
              {body.items.map((entry) => (
                <li
                  key={entry.id}
                  className="flex items-center gap-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2 py-1.5 text-xs"
                >
                  <span className="min-w-0 flex-1 truncate text-[var(--lumi-text-secondary)]">
                    {entry.voice} · {entry.model}
                  </span>
                  <span className="text-[var(--lumi-text-tertiary)]">
                    {formatBytes(entry.sizeBytes)}
                  </span>
                  <span className="text-[var(--lumi-text-tertiary)]">
                    {entry.createdAt.slice(0, 16).replace('T', ' ')}
                  </span>
                  <button
                    type="button"
                    aria-label="删除此条缓存"
                    onClick={() => removeOne.mutate(entry.id)}
                    className="text-[var(--lumi-text-tertiary)] hover:text-[var(--lumi-danger)]"
                  >
                    <Trash2 aria-hidden className="size-3.5" />
                  </button>
                </li>
              ))}
            </ul>
          )}
          <div className="flex items-center gap-2">
            <span className="text-xs text-[var(--lumi-text-tertiary)]">
              共 {body.count} 条 · {formatBytes(body.totalBytes)} / 上限 {formatBytes(body.capBytes)}
            </span>
            <div className="ml-auto">
              <Button
                size="sm"
                variant="ghost"
                className="text-[var(--lumi-danger, #dc2626)]"
                disabled={body.count === 0 || clearAll.isPending}
                onClick={() => clearAll.mutate()}
              >
                清空全部
              </Button>
            </div>
          </div>
        </>
      )}
      {notice !== null && (
        <p role="status" className="text-xs text-[var(--lumi-text-secondary)]">{notice}</p>
      )}
    </section>
  )
}
