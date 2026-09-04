/** 0018 备份页共享格式化 helpers —— Backup UI 各卡片共用。
 * 只做展示层格式化，不做任何数据变换。 */

import type { BackupJob, BackupJobStatus } from '../../../api/types'

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

export function formatBytes(bytes: number | undefined): string {
  if (bytes === undefined || bytes === null) return '—'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export function formatJobTime(iso: string | null): string {
  if (!iso) return '—'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return date.toLocaleString()
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
