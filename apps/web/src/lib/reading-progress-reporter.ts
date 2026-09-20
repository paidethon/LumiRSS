/** reading-progress-reporter — W3 阅读进度上报 hook（bundle 拆分收口）。
 *
 * 自 subscription-w3-panels 抽出：Reader 只需要这一个 hook，原先整块
 * 面板模块（订阅管理面板，依赖 tanstack queries 全集）被它拖进首屏
 * chunk。本文件只依赖 app-settings 与 client 的上报函数——entry 友好。
 * subscription-w3-panels 保留 re-export 兼容旧引用路径。 */

import { useEffect } from 'react'

import { putReadingProgress } from '../api/client'
import { useAppSettings } from '../store/app-settings'

/** 阅读进度上报（F049/W3）：滚动/离开页面节流上报当前段落与百分比；
 * pauseReadingProgress 开启或未打开文章时不挂任何监听。 */
export function useReadingProgressReporter(entryRef: string | null) {
  const settings = useAppSettings((s) => s.settings)
  const paused = settings.pauseReadingProgress === true
  useEffect(() => {
    if (entryRef === null || paused) return
    let lastPara = ''
    let lastPct = 0
    let lastSentAt = 0
    const send = (force = false) => {
      if (document.visibilityState !== 'visible') return
      if (lastPara === '') return
      const now = Date.now()
      if (!force && now - lastSentAt < 15_000) return
      lastSentAt = now
      void putReadingProgress({ entryRef, paraId: lastPara, pct: lastPct, deviceLabel: '' }).catch(
        () => {},
      )
    }
    const measure = () => {
      const container = document.querySelector('[data-reader-body]')
      if (!(container instanceof HTMLElement)) return
      const max = container.scrollHeight - container.clientHeight
      lastPct = max > 0 ? Math.min(100, Math.round((container.scrollTop / max) * 1000) / 10) : 0
      const current = container.querySelector('[data-para-id]')
      if (current instanceof HTMLElement) lastPara = current.dataset.paraId ?? ''
    }
    const onScroll = () => {
      if (document.visibilityState !== 'visible') return // 不可见标签页不上报
      measure()
      send()
    }
    const onLeave = () => send(true)
    const onVisible = () => {
      if (document.visibilityState === 'visible') measure()
    }
    window.addEventListener('pagehide', onLeave)
    document.addEventListener('visibilitychange', onVisible)
    document.addEventListener('scroll', onScroll, { passive: true, capture: true })
    return () => {
      window.removeEventListener('pagehide', onLeave)
      document.removeEventListener('visibilitychange', onVisible)
      document.removeEventListener('scroll', onScroll, { capture: true })
      measure()
      send(true)
    }
  }, [entryRef, paused])
}
