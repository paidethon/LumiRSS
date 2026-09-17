import { useEffect, useMemo, useRef, useState } from 'react'
import type { EntryDetail } from '../api/types'
import { renderArticleHtmlCached, sanitizeArticleHtmlCached } from '../lib/article-pipeline'
import { deferImages } from '../lib/article-images'
import { withHeadingIds } from '../lib/article-toc'
import { decorateCodeCopyButtons } from '../lib/code-copy'
import { useAppSettings } from '../store/app-settings'
import { prefersDarkScheme, resolveTheme } from '../lib/theme'
import ArticleToc from './ArticleToc'

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
  // F22 省流：hidden 模式下图片在进入 DOM 前摘掉 src（不发请求）；
  // imagesAllowed 是单篇覆盖（点「加载图片」后恢复本篇的真实地址）。
  // Reader 按 entryRef 重挂载（既定架构），覆盖状态天然不跨文章泄漏。
  const imageMode = useAppSettings((s) => s.settings.readerImageMode)
  const [imagesAllowed, setImagesAllowed] = useState(false)
  useEffect(() => {
    setImagesAllowed(false)
  }, [detail.entryRef])

  const rawHtml = detail.contentHtml ?? null
  const hasHtml = rawHtml !== null && rawHtml.trim() !== ''
  // 同步初值：管线关闭时直接 sanitize（零额外开销）；开启时先渲染
  // sanitize 基线、transform 完成后替换——加载期间正文可见不空白。
  // 缓存版：Reader 按 entryRef 重挂载（防 mutation 泄漏的既定架构），
  // 重挂载不重复付出整个正文的清洗成本（快速来回切换时尤其明显）。
  const [html, setHtml] = useState(() =>
    rawHtml !== null && rawHtml.trim() !== '' ? sanitizeArticleHtmlCached(rawHtml) : '',
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
    void renderArticleHtmlCached(rawHtml, {
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

  // 目录提取（pool #03）：在 DOMPurify 输出之上给 h2–h4 注入确定性 id
  // 并生成目录；输入已清洗，注入的只有 id 属性，无脚本注入面。
  // F22：hidden 且未单篇覆盖 → 摘除图片地址（不发请求），并统计数量；
  // 覆盖后 memo 重算，直接产回带 src 的版本（defer 结果不回写状态）。
  const { html: htmlWithIds, toc, deferredImageCount } = useMemo(() => {
    if (!hasHtml || html === '') return { html, toc: [], deferredImageCount: 0 }
    const withIds = withHeadingIds(html)
    if (imageMode !== 'hidden' || imagesAllowed) {
      return { html: withIds.html, toc: withIds.toc, deferredImageCount: 0 }
    }
    const deferred = deferImages(withIds.html)
    return { html: deferred.html, toc: withIds.toc, deferredImageCount: deferred.imageCount }
  }, [html, hasHtml, imageMode, imagesAllowed])

  // 代码块复制按钮（pool #04）：渲染后 DOM 装饰（幂等），html 变化
  // （管线重跑）后重装饰。
  const contentRef = useRef<HTMLDivElement | null>(null)
  useEffect(() => {
    const container = contentRef.current
    if (container === null || !hasHtml) return
    decorateCodeCopyButtons(container)
  }, [htmlWithIds, hasHtml])

  if (hasHtml) {
    return (
      <>
        <ArticleToc toc={toc} />
        {deferredImageCount > 0 ? (
          <div className="flex items-center gap-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] px-2.5 py-1.5 text-xs text-[var(--lumi-text-secondary)]">
            <span>省流模式：{deferredImageCount} 张图片未加载</span>
            <button
              type="button"
              onClick={() => setImagesAllowed(true)}
              className="text-[var(--lumi-accent-text)] underline-offset-2 hover:underline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
            >
              加载本文图片
            </button>
          </div>
        ) : null}
        <div
          ref={contentRef}
          className="article-content"
          // 注入的字符串永远是 DOMPurify 输出（唯一清洗点在
          // sanitize-article-html.ts；transforms 发生在 sanitize 之前；
          // withHeadingIds/deferImages 只在其上做属性级后处理）。
          dangerouslySetInnerHTML={{ __html: htmlWithIds }}
        />
      </>
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
