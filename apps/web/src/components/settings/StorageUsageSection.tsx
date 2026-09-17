/** StorageUsageSection — F36：存储用量（口径明确，只读统计）。
 *
 * 分类：数据库（主库+WAL/SHM）/ 媒体资产（含去重后占用）/ 本地备份。
 * 统计失败的分量为「未知」，不冒充零；预算提醒由服务端按
 * LUMIRSS_STORAGE_BUDGET_MB 计算——本组件只展示，绝不触发删除。 */

import { useQuery } from '@tanstack/react-query'

import { getStorageUsage } from '../../api/client'

function mb(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined) return '未知'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

export function StorageUsageSection() {
  const usage = useQuery({
    queryKey: ['storage', 'usage'],
    queryFn: ({ signal }) => getStorageUsage(signal),
    staleTime: 30_000,
  })
  if (usage.isPending) return null
  if (usage.isError || !usage.data) {
    return <p className="text-xs text-[var(--lumi-text-tertiary)]">存储用量统计失败。</p>
  }
  const { data } = usage
  return (
    <div className="py-3" data-storage-usage>
      <div className="text-sm font-medium text-[var(--lumi-text-primary)]">存储用量</div>
      <dl className="mt-2 divide-y divide-[var(--lumi-separator)] text-sm">
        <div className="flex items-center justify-between py-2">
          <dt className="text-[var(--lumi-text-secondary)]">数据库（主库 + WAL/SHM）</dt>
          <dd className="text-[var(--lumi-text-primary)]">{mb(data.database?.bytes)}</dd>
        </div>
        <div className="flex items-center justify-between py-2">
          <dt className="text-[var(--lumi-text-secondary)]">
            媒体资产（{data.libraryAssets?.count ?? '未知'} 个；去重后 {mb(data.libraryAssets?.uniqueBytes)}）
          </dt>
          <dd className="text-[var(--lumi-text-primary)]">{mb(data.libraryAssets?.bytes)}</dd>
        </div>
        <div className="flex items-center justify-between py-2">
          <dt className="text-[var(--lumi-text-secondary)]">
            本地备份（{data.backupsDir?.count ?? 0} 个文件）
          </dt>
          <dd className="text-[var(--lumi-text-primary)]">{mb(data.backupsDir?.bytes)}</dd>
        </div>
        <div className="flex items-center justify-between py-2">
          <dt className="font-medium text-[var(--lumi-text-primary)]">已知合计</dt>
          <dd className="font-medium text-[var(--lumi-text-primary)]">{mb(data.totalKnownBytes)}</dd>
        </div>
      </dl>
      {data.warning ? (
        <p className="mt-2 text-xs text-[var(--lumi-danger)]" role="status">
          {data.warning}
        </p>
      ) : null}
      {data.budgetMB === null || data.budgetMB === undefined ? (
        <p className="mt-1 text-xs text-[var(--lumi-text-tertiary)]">
          未设置预算（LUMIRSS_STORAGE_BUDGET_MB）；预算只用于提醒，不会自动删除任何内容。
        </p>
      ) : null}
    </div>
  )
}
