/** ArticleOutlineDialog — N068 结构视图（辅助朗读结构检查面板）。
 *
 * 面板本身即 AT 友好表面：真实 <ul>/<li> 列表语义、标题按钮可聚焦跳转、
 * 计数行文本化。内容来自 buildArticleOutline（sr-only / aria-hidden
 * 子树已剔除）。打开状态为设备本地偏好（lib/article-outline 读写），
 * 下次打开文章自动还原。 */

import { useEffect, useMemo, useRef, useState } from 'react'
import { readAnnotationsForEntry } from '../lib/annotations'
import {
  buildArticleOutline,
  writeStructureViewOpen,
  type OutlineHeading,
} from '../lib/article-outline'
import { Dialog } from './ui/Dialog'
import { cx } from './ui/cx'

/** 跳转到标题元素：滚动定位 + 焦点移交（读屏跟随焦点）。 */
function jumpToHeading(heading: HTMLElement): void {
  heading.scrollIntoView({ block: 'start' })
  if (heading.tabIndex < 0) heading.tabIndex = -1
  heading.focus({ preventScroll: true })
}

function OutlineList({
  headings,
  resolve,
}: {
  headings: OutlineHeading[]
  resolve: (heading: OutlineHeading) => HTMLElement | null
}) {
  return (
    <ul className="mt-1 flex flex-col gap-0.5" data-testid="outline-headings">
      {headings.map((heading) => (
        <li key={heading.key} style={{ paddingInlineStart: `${(heading.level - 1) * 0.75}rem` }}>
          <button
            type="button"
            data-outline-level={heading.level}
            onClick={() => {
              const el = resolve(heading)
              if (el !== null) jumpToHeading(el)
            }}
            className="w-full truncate rounded-[var(--lumi-radius-sm)] py-1.5 text-left text-[13px] text-[var(--lumi-text-secondary)] transition-colors duration-[var(--lumi-motion-fast)] hover:text-[var(--lumi-accent-text)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
          >
            <span aria-hidden="true" className="me-1 text-[10px] text-[var(--lumi-text-tertiary)]">
              h{heading.level}
            </span>
            {heading.text}
          </button>
        </li>
      ))}
    </ul>
  )
}

export function ArticleOutlineDialog({
  open,
  onClose,
  entryRef,
  getContainer,
}: {
  open: boolean
  onClose: () => void
  entryRef: string
  /** 正文容器惰性入口（.lumi-reader-article）；null = 诚实空态。 */
  getContainer: () => HTMLElement | null
}) {
  // 元素引用表（构建大纲时捕获；跳转按引用命中，标题没有 id 也可跳）。
  const elementsRef = useRef<Map<string, HTMLElement>>(new Map())
  // 首次挂载时 ref 可能尚未 attach（React 提交顺序）：挂载后补一次解析。
  const [attachTick, setAttachTick] = useState(0)
  useEffect(() => {
    if (open && getContainer() === null) setAttachTick((t) => t + 1)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  const annotationCount = useMemo(
    () => (open ? readAnnotationsForEntry(entryRef).length : 0),
    [open, entryRef],
  )

  const container = open ? getContainer() : null

  const outline = useMemo(() => {
    elementsRef.current = new Map()
    if (!open || container === null) return null
    const result = buildArticleOutline(container, annotationCount)
    // 按文档序对账：key → 元素引用（跳转用；容器换血时 resolve 落空）
    const domHeadings = Array.from(
      container.querySelectorAll('h1, h2, h3, h4, h5, h6'),
    ).filter(
      (el) =>
        el.closest(
          '[aria-hidden="true"], [hidden], .sr-only, [data-lumi-annotations-overlay], [data-lumi-annotations-cards], script, style, template',
        ) === null,
    )
    for (const heading of result.headings) {
      const el = domHeadings[heading.index]
      if (el instanceof HTMLElement) elementsRef.current.set(heading.key, el)
    }
    return result
    // attachTick 参与：ref 晚挂载时补一次解析（见上方 effect）。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, container, annotationCount, attachTick])

  // 关闭时持久化（打开状态也持久化——由 ReaderHeader 在 toggle 时写）。
  useEffect(() => {
    if (!open) writeStructureViewOpen(false)
  }, [open])

  if (!open) return null

  return (
    <Dialog open onClose={onClose} title="结构视图" panelClassName="max-w-lg">
      <div className="flex flex-col gap-3">
        {container === null ? (
          <p className="text-sm text-[var(--lumi-text-secondary)]" role="status">
            正文尚未就绪，无法提取结构。
          </p>
        ) : outline === null ? (
          <p className="text-sm text-[var(--lumi-text-secondary)]" role="status">
            结构提取失败。
          </p>
        ) : (
          <>
            <section aria-label="标题结构">
              <h4 className="text-xs font-medium text-[var(--lumi-text-tertiary)]">
                标题（{outline.headings.length}）
              </h4>
              {outline.headings.length === 0 ? (
                <p className="mt-1 text-xs text-[var(--lumi-text-tertiary)]">
                  本文没有可见标题。
                </p>
              ) : (
                <OutlineList
                  headings={outline.headings}
                  resolve={(heading) => elementsRef.current.get(heading.key) ?? null}
                />
              )}
            </section>
            <section
              aria-label="结构计数"
              data-testid="outline-counts"
              className={cx(
                'rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)]',
                'bg-[var(--lumi-surface)] px-2.5 py-2 text-xs leading-5 text-[var(--lumi-text-secondary)]',
              )}
            >
              <ul className="flex flex-wrap gap-x-3 gap-y-0.5">
                <li>链接 {outline.counts.links}</li>
                <li>图片 {outline.counts.images}</li>
                <li>表格 {outline.counts.tables}</li>
                <li>代码块 {outline.counts.codeBlocks}</li>
                <li>批注 {outline.counts.annotations}</li>
              </ul>
            </section>
          </>
        )}
      </div>
    </Dialog>
  )
}

export default ArticleOutlineDialog
