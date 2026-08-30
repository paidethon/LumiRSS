import { useEffect, useState } from 'react'
import type { EntryDetail } from '../api/types'
import { sanitizeArticleHtml } from '../lib/sanitize-article-html'
import { renderArticleHtml } from '../lib/article-pipeline'
import { useAppSettings } from '../store/app-settings'
import { prefersDarkScheme, resolveTheme } from '../lib/theme'

/** ArticleContent — 正文渲染边界（0006 建立；0012 Gate 4 升级为
 * presentation pipeline）。
 *
 * 渲染路径（Spec 冻结的三分支）：
 * 1. contentHtml 非空 → 0012 管线：raw HTML → inert DOM → 受控
 *    transforms（简繁转换 / 词首强调，DOM API only）→ DOMPurify
 *    （最终安全边界）→ dangerouslySetInnerHTML；
 *    transforms 全部关闭时退化为直接 sanitize（= 0006 原行为）。
 * 2. contentHtml 为 null/空白 → contentText 纯文本（React 正常文本
 *    渲染 + pre-wrap，不包装成 HTML）。
 * 3. 两者皆空 → 「这篇文章没有可显示的正文。」（不是 Error）。
 *
 * 安全不变式（0012 Spec 安全模型）：
 * - 本组件仍是全应用唯一允许 dangerouslySetInnerHTML 的位置；
 * - 注入的字符串永远来自 sanitizeArticleHtml（DOMPurify，唯一清洗点）
 *   的输出——transforms 只发生在 sanitize 之前的 inert DOM 上；
 * - 简繁转换永不修改 EntryDetail / TanStack Query cache（只作用于
 *   本地 inert 副本）。 */
export default function ArticleContent({ detail }: { detail: EntryDetail }) {
  const conversion = useAppSettings((s) => s.settings.readerChineseConversion)
  const bionic = useAppSettings((s) => s.settings.readerBionic)
  const codeHighlight = useAppSettings((s) => s.settings.readerCodeHighlight)
  const codeTheme = useAppSettings((s) => s.settings.readerCodeTheme)
  const themeMode = useAppSettings((s) => s.settings.themeMode)

  const rawHtml = detail.contentHtml
  const hasHtml = rawHtml !== null && rawHtml.trim() !== ''
  // 同步初值：管线关闭时直接 sanitize（零额外开销）；开启时先渲染
  // sanitize 基线、transform 完成后替换——加载期间正文可见不空白。
  const [html, setHtml] = useState(() =>
    rawHtml !== null && rawHtml.trim() !== '' ? sanitizeArticleHtml(rawHtml) : '',
  )

  // 代码主题解析：auto = 随当前应用主题明暗切换（system 模式下监听
  // 系统偏好变化以重跑高亮；其余主题名直接锁定）。
  const [systemDark, setSystemDark] = useState(prefersDarkScheme)
  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const onChange = (e: MediaQueryListEvent) => setSystemDark(e.matches)
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])
  const resolvedCodeTheme =
    codeHighlight === 'off'
      ? null
      : codeTheme === 'auto'
        ? resolveTheme(themeMode, systemDark) === 'dark'
          ? 'github-dark'
          : 'github-light'
        : codeTheme

  useEffect(() => {
    if (rawHtml === null || rawHtml.trim() === '') return
    let cancelled = false
    void renderArticleHtml(rawHtml, {
      conversion,
      bionic,
      codeTheme: resolvedCodeTheme,
    }).then((out) => {
      if (!cancelled) setHtml(out)
    })
    return () => {
      cancelled = true
    }
    // 设置变化 → 重跑管线（从 raw HTML，完全恢复语义）
  }, [
    rawHtml,
    detail.entryRef,
    conversion,
    bionic,
    resolvedCodeTheme,
  ])

  if (hasHtml) {
    return (
      <div
        className="article-content"
        // 注入的字符串永远是 DOMPurify 输出（唯一清洗点在
        // sanitize-article-html.ts；transforms 发生在 sanitize 之前）。
        dangerouslySetInnerHTML={{ __html: html }}
      />
    )
  }

  if (detail.contentText.trim() !== '') {
    return (
      <div className="article-content">
        <p className="whitespace-pre-wrap">{detail.contentText}</p>
      </div>
    )
  }

  return (
    <p className="article-content text-sm text-[var(--lumi-text-secondary)]">
      这篇文章没有可显示的正文。
    </p>
  )
}
