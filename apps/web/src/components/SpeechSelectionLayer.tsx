/** SpeechSelectionLayer — NF1 N091 「从选中句开始朗读」浮动入口。
 *
 * 监听正文内的文本选区：选区锚点能映射到当前收集的朗读块（见
 * lib/reader-speech 的 speechBlockIndexForSelection——排除开关命中的块
 * 不在收集结果里，代码/表格里的选区永不作为起点）时，在选区末端附近
 * 显示「从此处朗读」浮动按钮。点击调用 useSpeechControl.speakFromBlock：
 * 引擎 cancel-first（单通道），既有朗读自动停止，从该块开头入队。
 *
 * 定位用选区 getBoundingClientRect（视口坐标 + fixed 定位）；jsdom 下
 * 全为 0，测试只验证行为不验证像素。print:hidden 与全局打印规则（button
 * 不打印）双保险，浮动控件不进打印稿。mousedown preventDefault 维持
 * 选区——否则浏览器在按下时清除选区会先拆掉本按钮、click 不再发生
 * （与 AnnotationsLayer 浮动条同一交互形态）。 */

import { useCallback, useEffect, useState } from 'react'
import {
  speechBlockIndexForSelection,
  type SpeechCollection,
} from '../lib/reader-speech'

interface SelectionTarget {
  blockIndex: number
  x: number
  y: number
}

export function SpeechSelectionLayer({
  getBlocks,
  onSpeakFromBlock,
}: {
  /** 与 ReaderHeader/引擎同源的收集入口（含排除/词典后的块定位）。 */
  getBlocks: () => SpeechCollection | null
  onSpeakFromBlock: (blockIndex: number) => void
}) {
  const [target, setTarget] = useState<SelectionTarget | null>(null)

  const update = useCallback(() => {
    const sel = window.getSelection()
    if (
      sel === null ||
      sel.rangeCount === 0 ||
      sel.isCollapsed ||
      typeof sel.getRangeAt !== 'function'
    ) {
      setTarget(null)
      return
    }
    const container = document.querySelector('.lumi-reader-article')
    if (container === null) {
      setTarget(null)
      return
    }
    const collection = getBlocks()
    if (collection?.blocks === undefined || collection.blocks.length === 0) {
      setTarget(null)
      return
    }
    const blockIndex = speechBlockIndexForSelection(
      sel,
      container,
      collection.blocks,
    )
    if (blockIndex === null) {
      setTarget(null)
      return
    }
    const range = sel.getRangeAt(0)
    // jsdom 的 Range 没有 getBoundingClientRect：能力缺失时用零矩形
    // （行为可测，定位诚实降级到视口左上角）。
    const rect =
      typeof range.getBoundingClientRect === 'function'
        ? range.getBoundingClientRect()
        : { left: 0, top: 0, right: 0, bottom: 0 }
    setTarget({ blockIndex, x: rect.left, y: rect.bottom })
  }, [getBlocks])

  useEffect(() => {
    const onMouseUp = () => update()
    const container = document.querySelector('.lumi-reader-article')
    document.addEventListener('selectionchange', update)
    container?.addEventListener('mouseup', onMouseUp)
    container?.addEventListener('touchend', onMouseUp)
    return () => {
      document.removeEventListener('selectionchange', update)
      container?.removeEventListener('mouseup', onMouseUp)
      container?.removeEventListener('touchend', onMouseUp)
    }
  }, [update])

  if (target === null) return null
  return (
    <div
      data-lumi-speech-selection=""
      className="fixed z-40 print:hidden"
      style={{ top: Math.max(0, target.y + 6), left: Math.max(0, target.x) }}
    >
      <button
        type="button"
        data-lumi-speech-from-selection=""
        className="inline-flex min-h-11 items-center rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface-elevated)] px-3 text-sm text-[var(--lumi-text-primary)] shadow-[var(--lumi-shadow-popover)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
        onMouseDown={(event) => event.preventDefault()}
        onClick={() => {
          onSpeakFromBlock(target.blockIndex)
          window.getSelection()?.removeAllRanges()
          setTarget(null)
        }}
      >
        从此处朗读
      </button>
    </div>
  )
}

export default SpeechSelectionLayer
