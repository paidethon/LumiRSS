/** PositionCalibrationPanel — NEW-353 阅读位置手动校准面板。
 *
 * 跨设备恢复不准确时：用户选章节（select）→ 选段落（radio）→
 * 「以此为阅读位置」。保存 = 写入既有 reading-position 的本机位置记忆
 * （anchorText 精确锚点 + 当前落点 ratio）——恢复端零改动即生效。
 *
 * 诚实边界：校准只覆盖**本机**位置记忆（lumirss-reading-positions）；
 * 「跨设备同步」本身是尽力而为（锚点优先、ratio 回退），面板明确说明。
 * 段落超过上限时如实提示截断。 */

import { useMemo, useRef, useState } from 'react'
import { Check, X } from 'lucide-react'
import {
  CALIBRATION_PARAGRAPH_CAP,
  calibrationRatio,
  calibrationRestoreTop,
  collectCalibrationParagraphs,
  groupCalibrationByChapter,
} from '../../lib/reading-position-calibration'
import { saveReadingPosition, findAnchorElement } from '../../lib/reading-position'
import type { TocEntry } from '../../lib/article-toc'
import { IconButton } from '../ui/IconButton'

/** 面板内单章节渲染的段落上限（超出如实提示用章节缩小范围）。 */
const PARAGRAPHS_PER_CHAPTER_VIEW = 200

export interface PositionCalibrationPanelProps {
  entryRef: string
  /** 目录（可选；缺省时章节名来自段落收集时的标题文本）。 */
  toc?: TocEntry[]
  getArticle: () => HTMLElement | null
  getScroller: () => HTMLElement | null
  onClose: () => void
}

export function PositionCalibrationPanel({
  entryRef,
  toc = [],
  getArticle,
  getScroller,
  onClose,
}: PositionCalibrationPanelProps) {
  const paragraphs = useMemo(() => collectCalibrationParagraphs(getArticle()), [getArticle])
  const groups = useMemo(() => groupCalibrationByChapter(paragraphs, toc), [paragraphs, toc])
  const [chapterKey, setChapterKey] = useState<string>(() =>
    groups[0]?.id === null ? '__all__' : (groups[0]?.id ?? '__none__'),
  )
  const [selectedAnchor, setSelectedAnchor] = useState<string | null>(null)
  const [status, setStatus] = useState<'idle' | 'saved' | 'empty'>('idle')
  const copyTimerRef = useRef<number | undefined>(undefined)

  const activeGroup =
    groups.find((group) => (group.id === null ? chapterKey === '__all__' : group.id === chapterKey)) ??
    null
  const truncated = activeGroup !== null && activeGroup.paragraphs.length > PARAGRAPHS_PER_CHAPTER_VIEW
  const visibleParagraphs = activeGroup?.paragraphs.slice(0, PARAGRAPHS_PER_CHAPTER_VIEW) ?? []

  const save = () => {
    if (selectedAnchor === null) return
    const scroller = getScroller()
    const article = getArticle()
    const target = visibleParagraphs.find((p) => p.anchorText === selectedAnchor) ?? null
    if (target === null) return
    let ratio = 0
    // 用与恢复端同一公式找回落点（找不到元素 → ratio=0，锚点仍是主定位）
    const element = article !== null ? findAnchorElement(article, selectedAnchor) : null
    if (scroller !== null && element !== null) {
      const top = calibrationRestoreTop(
        element.getBoundingClientRect().top,
        scroller.getBoundingClientRect().top,
        scroller.scrollTop,
      )
      ratio = calibrationRatio(top, scroller.scrollHeight, scroller.clientHeight)
    }
    saveReadingPosition(entryRef, {
      ratio,
      anchorText: selectedAnchor,
      savedAt: new Date().toISOString(),
    })
    setStatus('saved')
    window.clearTimeout(copyTimerRef.current)
    copyTimerRef.current = window.setTimeout(() => setStatus('idle'), 2000)
  }

  return (
    <div
      role="dialog"
      aria-label="阅读位置校准"
      data-n353-panel=""
      className="absolute right-4 top-16 z-30 max-h-[70vh] w-[min(24rem,calc(100vw-2rem))] overflow-y-auto rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface-elevated)] p-3 shadow-lg"
    >
      <div className="mb-2 flex items-center gap-2">
        <p className="flex-1 text-xs font-medium text-[var(--lumi-text-primary)]">
          阅读位置校准
        </p>
        <IconButton size="sm" icon={<X aria-hidden className="size-4" />} label="关闭校准面板" touch onClick={onClose} />
      </div>

      {paragraphs.length === 0 ? (
        <p role="note" className="text-sm leading-relaxed text-[var(--lumi-text-secondary)]">
          正文尚未挂载或没有可校准的段落——打开文章正文后再试。
        </p>
      ) : (
        <div className="flex flex-col gap-3">
          <p className="text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
            跨设备恢复不准确时，直接选择章节和段落作为新的阅读位置
            （替代拖动滚动条）。
          </p>

          <label className="flex flex-col gap-1">
            <span className="text-xs font-medium text-[var(--lumi-text-primary)]">章节</span>
            <select
              data-testid="n353-chapter-select"
              aria-label="选择章节"
              value={chapterKey}
              onChange={(e) => {
                setChapterKey(e.target.value)
                setSelectedAnchor(null)
              }}
              className="min-h-11 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 text-sm text-[var(--lumi-text-primary)]"
            >
              {groups.map((group) => (
                <option key={group.id ?? '__all__'} value={group.id ?? '__all__'}>
                  {group.title}（{group.paragraphs.length} 段）
                </option>
              ))}
            </select>
          </label>

          <fieldset className="flex flex-col gap-1.5">
            <legend className="text-xs font-medium text-[var(--lumi-text-primary)]">段落</legend>
            {visibleParagraphs.map((paragraph) => (
              <label
                key={paragraph.index}
                data-n353-paragraph={paragraph.index}
                className="flex min-h-11 cursor-pointer items-start gap-2 rounded-[var(--lumi-radius-md)] px-1.5 py-1 hover:bg-[var(--lumi-surface-hover)]"
              >
                <input
                  type="radio"
                  name="n353-calibration-paragraph"
                  aria-label={`第 ${paragraph.index + 1} 段`}
                  checked={selectedAnchor === paragraph.anchorText}
                  onChange={() => setSelectedAnchor(paragraph.anchorText)}
                  className="mt-1 size-4 shrink-0 accent-[var(--lumi-accent)]"
                />
                <span className="min-w-0 text-xs leading-relaxed text-[var(--lumi-text-primary)]">
                  <span className="mr-1 tabular-nums text-[var(--lumi-text-tertiary)]">
                    {paragraph.index + 1}.
                  </span>
                  {paragraph.anchorText}
                </span>
              </label>
            ))}
            {truncated && (
              <p role="note" className="text-xs text-[var(--lumi-text-tertiary)]">
                本章节仅显示前 {PARAGRAPHS_PER_CHAPTER_VIEW} 段（共{' '}
                {activeGroup?.paragraphs.length} 段）。
              </p>
            )}
          </fieldset>

          {paragraphs.length >= CALIBRATION_PARAGRAPH_CAP && (
            <p role="note" className="text-xs text-[var(--lumi-text-tertiary)]">
              超长文：仅收集前 {CALIBRATION_PARAGRAPH_CAP} 个段落。
            </p>
          )}

          <div className="flex items-center gap-2">
            <button
              type="button"
              data-testid="n353-save"
              disabled={selectedAnchor === null}
              onClick={save}
              className="min-h-11 rounded-[var(--lumi-radius-md)] bg-[var(--lumi-accent-soft)] px-3 py-1.5 text-sm font-medium text-[var(--lumi-accent-text)] hover:bg-[var(--lumi-accent-soft)] disabled:cursor-not-allowed disabled:bg-transparent disabled:text-[var(--lumi-text-disabled)]"
            >
              以此为阅读位置
            </button>
            {status === 'saved' && (
              <span role="status" aria-live="polite" data-n353-saved="" className="flex items-center gap-1 text-xs text-[var(--lumi-success)]">
                <Check aria-hidden className="size-3.5" /> 已保存到本机位置记忆
              </span>
            )}
          </div>

          <p className="text-xs leading-relaxed text-[var(--lumi-text-tertiary)]">
            校准只更新本机的阅读位置记忆；跨设备同步仍为尽力而为
            （锚点优先、滚动比例回退），下次恢复将落到所选段落。
          </p>
        </div>
      )}
    </div>
  )
}

export default PositionCalibrationPanel
