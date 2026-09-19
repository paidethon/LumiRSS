/** AnnotationsLayer — F20 正文高亮/批注渲染层（自包含组件）。
 *
 * 集成约定：Reader.tsx 归集成方接线，本组件**自包含**——不依赖
 * props 传容器：优先 containerRef，否则自行 querySelector('.lumi-reader-article')，
 * 容器未就绪时观察 document.body 挂载，挂上后再观察正文变化重解析。
 *
 * 能力边界（诚实降级）：
 * - 高亮用 CSS Custom Highlight API（CSS.highlights + ::highlight()）；
 *   运行环境缺失（旧浏览器/jsdom）时**无高亮但不报错**，批注卡列表仍可见；
 * - 锚点解析失败（正文变化导致 prefix/exact/suffix 都找不到）时在卡片上
 *   诚实标注「锚点失效」，不假装命中；
 * - 存储为设备本地 localStorage（lib/annotations.ts），不谎称云同步，
 *   绝不写回 Obsidian vault。
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { AnnotationPopover } from './AnnotationPopover'
import { Button } from './ui/Button'
import {
  ANNOTATION_COLORS,
  articleText,
  computeContentVersion,
  createAnchor,
  deleteAnnotation,
  rangeFromHit,
  readAnnotationsForEntry,
  resolveAnchor,
  saveAnnotation,
  type Annotation,
  type AnnotationColor,
} from '../lib/annotations'

// ---- 常量 ----

/** ::highlight() 注册名前缀（完整名：lumi-annotation-yellow 等） */
const HIGHLIGHT_PREFIX = 'lumi-annotation'

/** 三色高亮底色（内容标注语义色，非主题 token；带透明度叠在正文上） */
const HIGHLIGHT_BG: Record<AnnotationColor, string> = {
  yellow: 'rgba(245, 217, 10, 0.45)',
  green: 'rgba(122, 199, 79, 0.40)',
  pink: 'rgba(244, 114, 182, 0.40)',
}

const COLOR_DOT: Record<AnnotationColor, string> = {
  yellow: '#eab308',
  green: '#65a30d',
  pink: '#ec4899',
}

const STYLE_TEXT = `
::highlight(${HIGHLIGHT_PREFIX}-yellow) { background-color: ${HIGHLIGHT_BG.yellow}; }
::highlight(${HIGHLIGHT_PREFIX}-green) { background-color: ${HIGHLIGHT_BG.green}; }
::highlight(${HIGHLIGHT_PREFIX}-pink) { background-color: ${HIGHLIGHT_BG.pink}; }
`

/** 稳定 id（crypto.randomUUID 不可用时退化为时间+随机） */
function newId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return `anno-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
}

/** CSS Custom Highlight API 可用性（jsdom/旧浏览器 → false，走无高亮降级） */
function supportsHighlights(): boolean {
  return (
    typeof CSS !== 'undefined' &&
    'highlights' in CSS &&
    typeof (globalThis as { Highlight?: unknown }).Highlight === 'function'
  )
}

function highlightRegistry(): Map<string, unknown> | null {
  if (!supportsHighlights()) return null
  return (CSS as unknown as { highlights: Map<string, unknown> }).highlights
}

export interface AnnotationsLayerProps {
  /** 所属条目（批注按 entryRef 归档） */
  entryRef: string
  /** 正文容器（缺省时组件自找 .lumi-reader-article） */
  containerRef?: React.RefObject<HTMLElement | null>
  /** 正文版本指纹（缺省时按容器文本现算） */
  contentVersion?: string
}

/** 解析结果（卡片渲染用；范围另存 ref 供跳回原文） */
interface ResolveResult {
  id: string
  lost: boolean
  stale: boolean
}

function sameResults(a: ResolveResult[], b: ResolveResult[]): boolean {
  return a.length === b.length && a.every((x, i) => x.id === b[i].id && x.lost === b[i].lost && x.stale === b[i].stale)
}

export function AnnotationsLayer({ entryRef, containerRef, contentVersion }: AnnotationsLayerProps) {
  const [annotations, setAnnotations] = useState<Annotation[]>([])
  const [results, setResults] = useState<ResolveResult[]>([])
  const [cardsNode, setCardsNode] = useState<HTMLElement | null>(null)
  // 正文 DOM 变化信号（MutationObserver 触发重解析）
  const [domTick, setDomTick] = useState(0)
  /** 正文内当前选区（非空文本）→ 浮动条 */
  const [selectionText, setSelectionText] = useState<string | null>(null)
  const [popover, setPopover] = useState<
    | { mode: 'create'; /** 打开弹层时克隆的选区（聚焦输入框会丢文档选区） */ range: Range }
    | { mode: 'edit'; annotation: Annotation }
    | null
  >(null)
  const [createError, setCreateError] = useState<string | null>(null)
  /** 已解析的 DOM Range（跳回原文用；失效条目不在表内） */
  const rangesRef = useRef<Map<string, Range>>(new Map())

  const findContainer = useCallback((): HTMLElement | null => {
    if (containerRef?.current) return containerRef.current
    return document.querySelector<HTMLElement>('.lumi-reader-article')
  }, [containerRef])

  // ---- 挂载：找容器 → 注入卡片挂载点 → 观察正文变化 ----
  useEffect(() => {
    let bodyObserver: MutationObserver | null = null
    let containerObserver: MutationObserver | null = null
    let node: HTMLElement | null = null

    const attach = (): boolean => {
      const container = findContainer()
      if (container === null) return false
      node = container.querySelector<HTMLElement>(':scope > [data-lumi-annotations-cards]')
      if (node === null) {
        node = document.createElement('div')
        node.setAttribute('data-lumi-annotations-overlay', 'true')
        node.setAttribute('data-lumi-annotations-cards', 'true')
        container.appendChild(node)
      }
      setCardsNode(node)
      // 正文任何变化（懒加载图片/翻译块/内容替换）→ 重解析锚点
      containerObserver = new MutationObserver(() => setDomTick((t) => t + 1))
      containerObserver.observe(container, { childList: true, subtree: true, characterData: true })
      setDomTick((t) => t + 1)
      return true
    }

    if (!attach()) {
      // 容器未就绪（Reader 异步渲染）：等 DOM 变化再挂
      bodyObserver = new MutationObserver(() => {
        if (attach()) {
          bodyObserver?.disconnect()
          bodyObserver = null
        }
      })
      bodyObserver.observe(document.body, { childList: true, subtree: true })
    }

    return () => {
      bodyObserver?.disconnect()
      containerObserver?.disconnect()
      node?.remove()
      setCardsNode(null)
    }
  }, [entryRef, findContainer])

  // ---- 载入本条目的批注（entryRef 切换时重读） ----
  useEffect(() => {
    setAnnotations(readAnnotationsForEntry(entryRef))
    setPopover(null)
    setSelectionText(null)
    rangesRef.current = new Map()
  }, [entryRef])

  const container = cardsNode?.parentElement ?? null

  // ---- 解析锚点 + 应用高亮 ----
  useEffect(() => {
    if (container === null) return
    const version = contentVersion ?? computeContentVersion(articleText(container))
    const next: ResolveResult[] = []
    const ranges = new Map<string, Range>()

    for (const a of annotations) {
      const hit = resolveAnchor(container, a.anchor)
      if (hit === null) {
        next.push({ id: a.id, lost: true, stale: false })
        continue
      }
      // 版本不一致但文本仍在：位置可能偏移，如实提示
      const stale = a.contentVersion !== '' && a.contentVersion !== version
      next.push({ id: a.id, lost: false, stale })
      const range = rangeFromHit(container, hit)
      if (range !== null) ranges.set(a.id, range)
    }

    rangesRef.current = ranges
    setResults((prev) => (sameResults(prev, next) ? prev : next))

    // 高亮注册（不支持的环境直接跳过 —— 无高亮但不报错）
    const registry = highlightRegistry()
    if (registry !== null) {
      const byColor: Record<AnnotationColor, Range[]> = { yellow: [], green: [], pink: [] }
      for (const [id, range] of ranges) {
        const a = annotations.find((x) => x.id === id)
        if (a) byColor[a.color].push(range)
      }
      for (const c of ANNOTATION_COLORS) {
        const key = `${HIGHLIGHT_PREFIX}-${c}`
        if (byColor[c].length > 0) registry.set(key, new (globalThis as { Highlight: new (...r: Range[]) => unknown }).Highlight(...byColor[c]))
        else registry.delete(key)
      }
    }
  }, [container, annotations, domTick, contentVersion])

  // 卸载时清理高亮注册，避免泄漏到下一篇正文
  useEffect(() => {
    const registry = highlightRegistry()
    return () => {
      if (registry === null) return
      for (const c of ANNOTATION_COLORS) registry.delete(`${HIGHLIGHT_PREFIX}-${c}`)
    }
  }, [])

  // ---- 选区监听：正文内选中文本 → 浮动创建条 ----
  useEffect(() => {
    if (container === null) return
    const update = () => {
      if (popover !== null) return
      const sel = window.getSelection()
      // jsdom/极老环境的 getSelection stub 无 getRangeAt：能力缺失时
      // 静默退出（批注列表仍可用，仅选区创建降级）。
      if (
        sel === null ||
        typeof sel.getRangeAt !== 'function' ||
        sel.isCollapsed ||
        sel.rangeCount === 0
      ) {
        setSelectionText(null)
        return
      }
      const range = sel.getRangeAt(0)
      const common = range.commonAncestorContainer
      const el = common.nodeType === Node.ELEMENT_NODE ? (common as Element) : common.parentElement
      if (el === null || !container.contains(el)) {
        setSelectionText(null)
        return
      }
      const text = range.toString()
      setSelectionText(text.trim() === '' ? null : text)
    }
    const onMouseUp = () => update()
    document.addEventListener('selectionchange', update)
    container.addEventListener('mouseup', onMouseUp)
    container.addEventListener('touchend', onMouseUp)
    return () => {
      document.removeEventListener('selectionchange', update)
      container.removeEventListener('mouseup', onMouseUp)
      container.removeEventListener('touchend', onMouseUp)
    }
  }, [container, popover])

  // ---- 操作 ----

  const refresh = useCallback(() => {
    setAnnotations(readAnnotationsForEntry(entryRef))
  }, [entryRef])

  const handleCreateSave = (note: string, color: AnnotationColor, range: Range) => {
    const target = container
    if (target === null) {
      setCreateError('正文容器未就绪，请关闭后重试。')
      return
    }
    const created = createAnchor(target, range)
    if (created === null) {
      setCreateError('选区已失效，请重新选择正文文字。')
      return
    }
    const annotation: Annotation = {
      id: newId(),
      entryRef,
      color,
      note,
      anchor: created.anchor,
      createdAt: Date.now(),
      contentVersion: contentVersion ?? computeContentVersion(articleText(target)),
    }
    saveAnnotation(annotation)
    window.getSelection()?.removeAllRanges()
    setCreateError(null)
    setPopover(null)
    setSelectionText(null)
    refresh()
  }

  const handleEditSave = (note: string, color: AnnotationColor, original: Annotation) => {
    saveAnnotation({ ...original, note, color })
    setPopover(null)
    refresh()
  }

  const handleDelete = (id: string) => {
    deleteAnnotation(id)
    refresh()
  }

  const handleJump = (id: string) => {
    const range = rangesRef.current.get(id)
    if (range === undefined) return
    const start = range.startContainer
    const el = start.nodeType === Node.ELEMENT_NODE ? (start as Element) : start.parentElement
    el?.scrollIntoView({ block: 'center', behavior: 'smooth' })
  }

  const resultById = new Map(results.map((r) => [r.id, r]))

  const cards = (
    <section
      aria-label="文章批注"
      className="mt-8 border-t border-[var(--lumi-separator)] pt-4"
    >
      <h4 className="text-sm font-semibold text-[var(--lumi-text-primary)]">
        批注（{annotations.length}）
      </h4>
      {annotations.length === 0 ? (
        <p className="mt-2 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
          本文还没有批注。选中正文文字即可创建（仅保存在本设备，不会同步）。
        </p>
      ) : (
        <ul className="mt-2 space-y-2.5">
          {annotations.map((a) => {
            const r = resultById.get(a.id)
            const lost = r?.lost === true
            return (
              <li
                key={a.id}
                className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-3"
              >
                <div className="flex items-start gap-2">
                  <span
                    aria-hidden
                    className="mt-1 block size-2.5 shrink-0 rounded-full"
                    style={{ backgroundColor: COLOR_DOT[a.color] }}
                  />
                  <div className="min-w-0 flex-1">
                    <blockquote className="line-clamp-3 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
                      {a.anchor.exact}
                    </blockquote>
                    {a.note !== '' && (
                      <p className="mt-1 text-sm leading-relaxed text-[var(--lumi-text-primary)]">
                        {a.note}
                      </p>
                    )}
                    {lost && (
                      <p className="mt-1 text-xs text-[var(--lumi-danger, #dc2626)]" role="status">
                        锚点失效：正文已变化，未能定位该批注的原文位置。
                      </p>
                    )}
                    {!lost && r?.stale === true && (
                      <p className="mt-1 text-xs text-[var(--lumi-text-tertiary)]">
                        正文与创建时版本不一致，位置可能有偏移。
                      </p>
                    )}
                    <div className="mt-2 flex flex-wrap items-center gap-2">
                      <Button
                        variant="secondary"
                        size="sm"
                        className="min-h-11"
                        disabled={lost}
                        onClick={() => handleJump(a.id)}
                      >
                        跳回原文
                      </Button>
                      <Button
                        variant="secondary"
                        size="sm"
                        className="min-h-11"
                        onClick={() => setPopover({ mode: 'edit', annotation: a })}
                      >
                        编辑
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="min-h-11 text-[var(--lumi-danger, #dc2626)]"
                        onClick={() => handleDelete(a.id)}
                      >
                        删除
                      </Button>
                    </div>
                  </div>
                </div>
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )

  return (
    <>
      {/* ::highlight() 样式（不支持的环境规则无效但无害） */}
      <style>{STYLE_TEXT}</style>
      {cardsNode !== null && createPortal(cards, cardsNode)}
      {/* 选区浮动条（固定顶部条，简化定位） */}
      {selectionText !== null && popover === null &&
        createPortal(
          <div
            role="toolbar"
            aria-label="批注操作"
            className="fixed inset-x-2 top-3 z-50 mx-auto flex max-w-md items-center justify-between gap-3 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-3 py-2 shadow-lg"
          >
            <p className="min-w-0 flex-1 truncate text-xs text-[var(--lumi-text-secondary)]">
              {createError ?? `已选中「${selectionText.slice(0, 16)}${selectionText.length > 16 ? '…' : ''}」`}
            </p>
            <Button
              variant="primary"
              size="sm"
              className="min-h-11"
              onClick={() => {
                // 打开弹层前克隆选区：聚焦备注输入框会丢失文档选区
                const sel = window.getSelection()
                if (sel === null || sel.rangeCount === 0 || sel.isCollapsed) {
                  setCreateError('选区已失效，请重新选择正文文字。')
                  return
                }
                setCreateError(null)
                setPopover({ mode: 'create', range: sel.getRangeAt(0).cloneRange() })
              }}
            >
              创建批注
            </Button>
            <Button
              variant="ghost"
              size="sm"
              className="min-h-11"
              onClick={() => {
                setCreateError(null)
                setSelectionText(null)
                window.getSelection()?.removeAllRanges()
              }}
            >
              取消
            </Button>
          </div>,
          document.body,
        )}
      {popover !== null &&
        createPortal(
          <AnnotationPopover
            initialNote={popover.mode === 'edit' ? popover.annotation.note : ''}
            initialColor={popover.mode === 'edit' ? popover.annotation.color : 'yellow'}
            onSave={(note, color) => {
              if (popover.mode === 'create') handleCreateSave(note, color, popover.range)
              else handleEditSave(note, color, popover.annotation)
            }}
            onCancel={() => {
              setCreateError(null)
              setPopover(null)
            }}
          />,
          document.body,
        )}
    </>
  )
}

export default AnnotationsLayer
