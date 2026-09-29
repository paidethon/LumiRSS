/** FieldHitBadges — NEW-363 跨字段命中说明（结果行内徽标）。
 *
 * 数据来自 POST /search/field-hits（父级对可见结果批量请求后逐行
 * 传入）：标题/正文/作者/来源/本人笔记。点击徽标 = 交给父级定位到
 * 相应字段（正文偏移走既有 F072 暂存定位；本人笔记列附带摘录）。
 */

import { Info } from 'lucide-react'
import type { FieldHitItem } from '../../api/new361'
import { cx } from '../ui/cx'

export const FIELD_LABELS: Record<string, string> = {
  title: '标题',
  content: '正文',
  author: '作者',
  feed: '来源',
  note: '本人笔记',
}

const FIELD_ORDER = ['title', 'content', 'author', 'feed', 'note']

export function FieldHitBadges({
  hit,
  onLocate,
}: {
  /** 该行的命中字段归位（父级批量 field-hits 的对应项；未取到 → null）。 */
  hit: FieldHitItem | null | undefined
  onLocate: (field: string, noteExcerpt: string | null) => void
}) {
  if (!hit || hit.fields.length === 0) return null
  const ordered = FIELD_ORDER.filter((field) => hit.fields.includes(field))
  return (
    <span
      data-testid="n363-field-hits"
      role="group"
      aria-label="命中字段（点击定位）"
      className="flex flex-wrap items-center gap-1"
    >
      {ordered.map((field) => (
        <button
          key={field}
          type="button"
          data-testid={`n363-field-${field}`}
          onClick={() =>
            onLocate(field, field === 'note' ? (hit.noteHit?.excerpt ?? null) : null)
          }
          title={`命中${FIELD_LABELS[field] ?? field}，点击定位`}
          className={cx(
            'min-h-6 rounded-[var(--lumi-radius-full)] px-1.5 py-0.5 text-xs',
            'bg-[var(--lumi-surface-selected)] text-[var(--lumi-text-secondary)]',
            'transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)]',
            'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
          )}
        >
          {FIELD_LABELS[field] ?? field}
          {field === 'note' && hit.noteHit !== null && ` ·${hit.noteHit.count}`}
        </button>
      ))}
      {hit.noteHit !== null && (
        <span
          className="inline-flex items-center gap-0.5 text-xs text-[var(--lumi-text-tertiary)]"
          title="笔记命中摘录"
        >
          <Info aria-hidden className="size-3" />
          {hit.noteHit.excerpt}
        </span>
      )}
    </span>
  )
}
