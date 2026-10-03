/** builtin-fonts — R08 内置阅读字体加载状态（FontFaceSet 桥）。
 *
 * 字体本体由 styles/fonts.css 以 @font-face + unicode-range 声明、
 * public/fonts/ 自托管：默认零加载（无 preload），只有当
 * ① 用户在阅读设置选中该字体（正文渲染命中分片）或
 * ② 设置里渲染该字体的样张预览
 * 时，浏览器才按 unicode-range 拉取命中的分片。
 *
 * 本模块只负责把 FontFaceSet 的加载态转成 UI 可消费的三态：
 * loading（含未开始）→ loaded / error。占位与回退由组件层处理。
 *
 * 环境守卫：document.fonts 缺失（极端内核/测试环境）→ 视为 loaded，
 * 组件直接按回退栈渲染样张，不显示永远不消失的占位。 */

import { useEffect, useState } from 'react'

export type BuiltinFontLoadState = 'loading' | 'loaded' | 'error'

/** 样张是否已全部可显示（已加载或环境不支持 FontFaceSet）。 */
function isLoaded(cssFamily: string, sample: string): boolean {
  try {
    if (typeof document === 'undefined' || document.fonts === undefined) return true
    return document.fonts.check(`16px "${cssFamily}"`, sample)
  } catch {
    return true
  }
}

/** 触发按需加载并跟踪状态（样张文本 → 仅命中其 unicode-range 的分片）。 */
export function useBuiltinFontState(cssFamily: string, sample: string): BuiltinFontLoadState {
  const [state, setState] = useState<BuiltinFontLoadState>(() =>
    isLoaded(cssFamily, sample) ? 'loaded' : 'loading',
  )

  useEffect(() => {
    if (isLoaded(cssFamily, sample)) {
      setState('loaded')
      return
    }
    let cancelled = false
    setState('loading')
    const load = (): Promise<unknown> =>
      typeof document === 'undefined' || document.fonts === undefined
        ? Promise.resolve([])
        : document.fonts.load(`16px "${cssFamily}"`, sample)
    load()
      .then(() => {
        if (!cancelled) setState('loaded')
      })
      .catch(() => {
        if (!cancelled) setState('error')
      })
    return () => {
      cancelled = true
    }
  }, [cssFamily, sample])

  return state
}
