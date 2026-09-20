/** DraftRestoreBar — F119 草稿恢复条（恢复 / 放弃 / 对照三选）。
 *
 * 打开表单时若存在较新的本机草稿（draft-store，白名单注册表单），
 * 在表单上方展示一条恢复提示：不自动覆盖用户当前输入——由用户显式
 * 选择「恢复」（采纳草稿值）、「放弃」（删除草稿）或「对照」（逐字段
 * 并排查看草稿 vs 当前值）。 */

import { useState } from 'react'

import { diffDraft, type DraftRecord } from '../lib/draft-store'
import { formatTimestamp } from '../lib/date-format'
import { Button } from './ui/Button'

export function DraftRestoreBar({
  draft,
  current,
  onAdopt,
  onDiscard,
}: {
  draft: DraftRecord
  current: Record<string, string>
  onAdopt: () => void
  onDiscard: () => void
}) {
  const [diffOpen, setDiffOpen] = useState(false)
  const rows = diffDraft(draft, current)
  return (
    <div
      role="status"
      className="flex flex-col gap-1.5 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-accent)]/40 bg-[var(--lumi-accent-soft)] px-2.5 py-2"
      data-draft-restore=""
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="min-w-0 flex-1 text-xs text-[var(--lumi-text-primary)]">
          有本机未保存草稿（{formatTimestamp(draft.updatedAt) || '时间未知'}保存）——恢复、放弃或先对照？
        </span>
        <Button variant="primary" size="sm" data-draft-adopt="" onClick={onAdopt}>
          恢复
        </Button>
        <Button variant="ghost" size="sm" data-draft-diff-toggle="" onClick={() => setDiffOpen((v) => !v)}>
          {diffOpen ? '收起对照' : '对照'}
        </Button>
        <Button variant="ghost" size="sm" data-draft-discard="" onClick={onDiscard}>
          放弃
        </Button>
      </div>
      {diffOpen && (
        <ul className="flex flex-col gap-0.5" data-draft-diff="">
          {rows.map((row) => (
            <li key={row.field} className="text-[11px] text-[var(--lumi-text-secondary)]">
              <span className="font-medium text-[var(--lumi-text-primary)]">{row.field}</span>：草稿{' '}
              {row.draftValue === '' ? '（空）' : row.draftValue.slice(0, 60)} / 当前{' '}
              {row.currentValue === '' ? '（空）' : row.currentValue.slice(0, 60)}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
