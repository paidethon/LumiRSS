/** 0018 备份页共享格式化 helpers —— Backup UI 各卡片共用。
 * 只做展示层格式化，不做任何数据变换。 */

import type { BackupJob, BackupJobStatus } from '../../../api/types'
import { formatTimestamp } from '../../../lib/date-format'

export const JOB_STATUS_LABELS: Record<BackupJobStatus, string> = {
  queued: '排队中',
  running: '进行中',
  succeeded: '已成功',
  failed: '失败',
  interrupted: '已中断',
}

export const JOB_TYPE_LABELS: Record<BackupJob['type'], string> = {
  full: '完整备份',
  safety: '安全备份',
  restore: '恢复',
}

/** BFF 真实 stage 值（backup.py update_stage）→ 中文文案。未知值原样显示。 */
export const STAGE_LABELS: Record<string, string> = {
  queued: '排队中',
  'backing-up-lumi-database': '正在备份 Lumi 数据库',
  'backing-up-freshrss': '正在备份 FreshRSS 数据',
  'building-archive': '正在打包归档',
  uploading: '正在上传 WebDAV',
  completed: '已完成',
}

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null) return '—'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export function formatJobTime(iso: string | null): string {
  if (!iso) return '—'
  const formatted = formatTimestamp(iso)
  return formatted || iso
}

export function jobStageText(job: BackupJob): string {
  if (job.status === 'running' && job.stage) {
    return STAGE_LABELS[job.stage] ?? job.stage
  }
  return JOB_STATUS_LABELS[job.status]
}

export const COMPONENT_LABELS: Record<string, string> = {
  'lumi.sqlite': 'Lumi 数据（设置 / AI 缓存 / 对话）',
  'freshrss-data': 'FreshRSS 数据（订阅 / 文章状态）',
}

export function componentLabel(component: string): string {
  return COMPONENT_LABELS[component] ?? component
}

/** 能力预检 reasonCode（BFF assess_freshrss_backup）→ 用户可操作的中文说明。
 * 未知 code 回退到服务端 reason（英文安全文案），不吞掉真实状态。 */
export const FRESHRSS_REASON_HINTS: Record<string, string> = {
  not_configured:
    '未配置 FreshRSS 数据目录：生产 Compose 已自动挂载；开发部署需在 BFF 的 .env 设置 FRESHRSS_DATA_DIR 指向宿主机可读的 FreshRSS data 目录。',
  path_missing: '配置的 FreshRSS 数据目录不存在，请检查挂载与路径配置。',
  not_a_directory: '配置的 FreshRSS 数据路径不是目录，请检查 FRESHRSS_DATA_DIR。',
  not_readable: 'BFF 进程没有读取 FreshRSS 数据目录的权限，请检查挂载与文件权限。',
  invalid_data_dir:
    '该目录缺少 config.php / users，不像有效的 FreshRSS 数据目录，请确认路径指向 FreshRSS 的 data 目录本身。',
  external_database:
    'FreshRSS 使用外部 MySQL/PostgreSQL 数据库：数据目录不含文章数据，完整备份不支持此拓扑，请直接备份数据库。',
  unreadable_entries: 'FreshRSS 数据目录内部分文件不可读，请检查文件权限。',
}

export function freshrssReasonText(
  reasonCode: string | null | undefined,
  fallback: string | null | undefined,
): string | null {
  if (!reasonCode) return null
  return FRESHRSS_REASON_HINTS[reasonCode] ?? fallback ?? reasonCode
}
