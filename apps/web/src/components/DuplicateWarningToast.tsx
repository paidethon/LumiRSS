/** N047 收录撞车提示 toast（workspace / 稍后读加入路径）。
 *
 * 服务端在 add 响应里附带 canonical URL 撞车提示（非阻断——条目已
 * 加入）；本 toast 订阅 useAddWorkspaceItemMutation 写入的独立 query
 * key，提供「定位」（打开已收录条目）与「仍要加入」（关闭）。
 * 只比 canonical URL，绝不因标题相似而提示。
 */

import { useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, X } from 'lucide-react'
import { DUPLICATE_WARNING_KEY, type DuplicateWarningPayload } from '../api/queries'
import { Button } from './ui/Button'

/** rss:<entryRef> → 裸 entryRef；非 rss ref 返回 null（阅读器打开用）。 */
function toEntryRefLoose(itemRef: string): string | null {
  return itemRef.startsWith('rss:') ? itemRef.slice(4) : null
}

export function DuplicateWarningToast({
  onLocate,
}: {
  onLocate?: (entryRef: string) => void
}) {
  const queryClient = useQueryClient()
  // useQuery 订阅同一 key：mutation 写入即触发渲染（读路径绝不发请求）。
  const { data: warning } = useQuery<DuplicateWarningPayload | null>({
    queryKey: DUPLICATE_WARNING_KEY,
    queryFn: () => queryClient.getQueryData<DuplicateWarningPayload>(DUPLICATE_WARNING_KEY) ?? null,
    staleTime: Infinity,
    gcTime: Infinity,
  })
  if (warning === null || warning === undefined) return null
  return (
    <div
      role="alert"
      data-testid="workspace-duplicate-warning"
      className="mx-4 mb-2 flex flex-wrap items-center gap-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-accent-soft)] px-2.5 py-1.5 text-xs"
    >
      <AlertTriangle aria-hidden className="size-3.5 text-[var(--lumi-accent-text)]" />
      <span className="min-w-0 flex-1 text-[var(--lumi-accent-text)]">
        疑似已收录：{warning.duplicateWarning.duplicateOf.title ?? warning.duplicateWarning.duplicateOf.ref}
      </span>
      <Button
        size="sm"
        variant="secondary"
        onClick={() => {
          const entryRef = toEntryRefLoose(warning.duplicateWarning.duplicateOf.ref)
          queryClient.setQueryData(DUPLICATE_WARNING_KEY, null)
          if (entryRef !== null && onLocate !== undefined) onLocate(entryRef)
        }}
      >
        定位
      </Button>
      <Button
        size="sm"
        variant="ghost"
        aria-label="仍要加入"
        onClick={() => queryClient.setQueryData(DUPLICATE_WARNING_KEY, null)}
      >
        <X aria-hidden className="size-3" />
        仍要加入
      </Button>
    </div>
  )
}

export default DuplicateWarningToast
