/** AnnotationPopover — F20 批注编辑浮层。
 *
 * 简化交互：固定顶部条（不跟随选区精确定位，避免滚动/缩放下的
 * 定位抖动）。输入备注 + 三色选择 + 保存/取消；Escape 取消；
 * 控件满足 44px 触控目标。颜色只影响本设备上的高亮底色。 */

import { useEffect, useId, useMemo, useRef, useState } from 'react'

import { clearDraft, loadDraftIfNewer, saveDraft, type DraftRecord } from '../lib/draft-store'
import { DraftRestoreBar } from './DraftRestoreBar'
import { Button } from './ui/Button'
import { cx } from './ui/cx'
import type { AnnotationColor } from '../lib/annotations'
import { ANNOTATION_COLORS } from '../lib/annotations'

/** 三色在 UI 里的呈现（高亮底色 + 色点），走语义观感而非硬编码全站色：
 *  批注色是内容标注语义，允许固定色值（非主题色）。 */
const COLOR_SWATCH: Record<AnnotationColor, string> = {
  yellow: '#f5d90a',
  green: '#7ac74f',
  pink: '#f472b6',
}

const COLOR_LABEL: Record<AnnotationColor, string> = {
  yellow: '黄色',
  green: '绿色',
  pink: '粉色',
}

export interface AnnotationPopoverProps {
  /** 初始备注（编辑已有批注时回填） */
  initialNote?: string
  /** 初始颜色（编辑时回填；新建默认 yellow） */
  initialColor?: AnnotationColor
  onSave: (note: string, color: AnnotationColor) => void
  onCancel: () => void
  /** N074：记为问题（编辑已有批注时提供；取当前备注文本）。 */
  onMarkQuestion?: (question: string) => void
}

export function AnnotationPopover({
  initialNote = '',
  initialColor = 'yellow',
  onSave,
  onCancel,
  onMarkQuestion,
}: AnnotationPopoverProps) {
  const [note, setNote] = useState(initialNote)
  const [color, setColor] = useState<AnnotationColor>(initialColor)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const noteId = useId()
  const groupId = useId()
  // F119：批注备注草稿（白名单 'annotation-editor'；无「已保存版本」
  // 基线 → savedAt=null，任何现存草稿都可恢复）。
  const draft = useMemo<DraftRecord | null>(
    () => loadDraftIfNewer('annotation-editor', null),
    // 挂载时一次性判定
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  )
  const [draftVisible, setDraftVisible] = useState(draft !== null)
  useEffect(() => {
    saveDraft('annotation-editor', { note })
  }, [note])

  // 打开即聚焦备注框；Escape 取消（不打断所在页面的其它行为）
  useEffect(() => {
    textareaRef.current?.focus()
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation()
        onCancel()
      }
    }
    document.addEventListener('keydown', onKeyDown, true)
    return () => document.removeEventListener('keydown', onKeyDown, true)
  }, [onCancel])

  return (
    <div
      role="dialog"
      aria-label="批注"
      className="fixed inset-x-2 top-14 z-50 mx-auto max-w-md rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-3 shadow-lg"
    >
      {draftVisible && draft !== null ? (
        <div className="mb-2">
          <DraftRestoreBar
            draft={draft}
            current={{ note }}
            onAdopt={() => {
              setNote(draft.values.note ?? note)
              clearDraft('annotation-editor')
              setDraftVisible(false)
            }}
            onDiscard={() => {
              clearDraft('annotation-editor')
              setDraftVisible(false)
            }}
          />
        </div>
      ) : null}
      <div>
        <label
          htmlFor={noteId}
          className="text-sm font-medium text-[var(--lumi-text-primary)]"
        >
          批注备注
        </label>
        <textarea
          ref={textareaRef}
          id={noteId}
          value={note}
          onChange={(e) => setNote(e.target.value)}
          rows={3}
          placeholder="写点想法（可留空，仅高亮）"
          className="mt-1.5 w-full resize-y rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-reader-bg,transparent)] px-2.5 py-2 text-sm text-[var(--lumi-text-primary)] focus-visible:outline-2 focus-visible:outline-[var(--lumi-focus-ring)]"
        />
      </div>
      <div className="mt-2.5" role="radiogroup" aria-labelledby={groupId}>
        <span id={groupId} className="text-sm font-medium text-[var(--lumi-text-primary)]">
          颜色
        </span>
        <div className="mt-1.5 flex items-center gap-2">
          {ANNOTATION_COLORS.map((c) => {
            const checked = color === c
            return (
              <button
                key={c}
                type="button"
                role="radio"
                aria-checked={checked}
                aria-label={COLOR_LABEL[c]}
                onClick={() => setColor(c)}
                className={cx(
                  'flex size-11 items-center justify-center rounded-full border-2 transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
                  checked ? 'border-[var(--lumi-accent)]' : 'border-transparent',
                )}
              >
                <span
                  aria-hidden
                  className={cx('block size-6 rounded-full', checked && 'ring-2 ring-white/70')}
                  style={{ backgroundColor: COLOR_SWATCH[c] }}
                />
              </button>
            )
          })}
        </div>
      </div>
      <div className="mt-3 flex items-center justify-end gap-2">
        {onMarkQuestion !== undefined && (
          <Button
            variant="secondary"
            className="min-h-11"
            onClick={() => onMarkQuestion(note.trim())}
          >
            记为问题
          </Button>
        )}
        <Button variant="secondary" className="min-h-11" onClick={onCancel}>
          取消
        </Button>
        <Button
          variant="primary"
          className="min-h-11"
          onClick={() => {
            clearDraft('annotation-editor')
            onSave(note.trim(), color)
          }}
        >
          保存批注
        </Button>
      </div>
    </div>
  )
}

export default AnnotationPopover
