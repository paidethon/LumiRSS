import { lazy, Suspense, useEffect, useMemo, useRef, useState } from 'react'
import type { EntryDetail } from '../api/types'
import { renderArticleHtmlCached, sanitizeArticleHtmlCached } from '../lib/article-pipeline'
import { deferImages } from '../lib/article-images'
import { withHeadingIds } from '../lib/article-toc'
import { decorateCodeCopyButtons } from '../lib/code-copy'
import { TABLE_WIDE_EXTRA_PX } from '../lib/reader-tools'
import { useAppSettings } from '../store/app-settings'
import { prefersDarkScheme, resolveTheme } from '../lib/theme'
import ArticleToc from './ArticleToc'
import type { LightboxImage } from './ArticleLightbox'

// Bundle guard：灯箱只在点击图片/表格展开时可见——懒加载分包。
const ArticleLightbox = lazy(() => import('./ArticleLightbox'))

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
 *   本地 inert 副本）。
 *
 * 渲染后装饰（F14/F15/F16）：
 * - 图片灯箱：给正文 img 接 zoom-in 点击（data-lumi-lightbox-ready
 *   防重复接线；hidden 模式不接线——无图可点，不偷偷加载）；
 * - 代码换行：readerCodeWrap 写到 html[data-code-wrap]，CSS 消费；
 * - 表格展开：过宽表格（scrollWidth > clientWidth + 24 或手动
 *   data-table-wide 标记，jsdom 无布局的测试注入点）包「展开查看」
 *   按钮，点击在灯箱面板中完整查看（横向可滚、保留语义表格）。 */
export default function ArticleContent({ detail }: { detail: EntryDetail }) {
  const conversion = useAppSettings((s) => s.settings.readerChineseConversion)
  const bionic = useAppSettings((s) => s.settings.readerBionic)
  const codeHighlight = useAppSettings((s) => s.settings.readerCodeHighlight)
  const codeTheme = useAppSettings((s) => s.settings.readerCodeTheme)
  const themeMode = useAppSettings((s) => s.settings.themeMode)
  // F15：代码自动换行（html[data-code-wrap] → index.css 规则）。
  const codeWrap = useAppSettings((s) => s.settings.readerCodeWrap)
  // F22 省流：hidden 模式下图片在进入 DOM 前摘掉 src（不发请求）；
  // imagesAllowed 是单篇覆盖（点「加载图片」后恢复本篇的真实地址）。
  // Reader 按 entryRef 重挂载（既定架构），覆盖状态天然不跨文章泄漏。
  const imageMode = useAppSettings((s) => s.settings.readerImageMode)
  const [imagesAllowed, setImagesAllowed] = useState(false)
  useEffect(() => {
    setImagesAllowed(false)
  }, [detail.entryRef])

  // F14：图片灯箱状态；F16：表格展开面板状态。打开前保存滚动容器
  // scrollTop，关闭后还原（面板不改变正文阅读位置）。
  const [lightbox, setLightbox] = useState<{ images: LightboxImage[]; index: number } | null>(null)
  const [tablePanel, setTablePanel] = useState<{ table: HTMLTableElement } | null>(null)
  const savedScrollRef = useRef<number | null>(null)
  const lastImageRef = useRef<HTMLImageElement | null>(null)
  const tableHostRef = useRef<HTMLDivElement | null>(null)

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

  // dangerouslySetInnerHTML 的 props 对象必须引用稳定：内联字面量在每次
  // 渲染都是新对象，React 更新该宿主元素时会重设 innerHTML——渲染后
  // DOM 装饰（复制按钮 / F14 灯箱标记 / F16 表格展开）随之被清掉。
  // memo 稳定对象后，仅在 htmlWithIds 变化时才真正重设。
  const htmlProp = useMemo(() => ({ __html: htmlWithIds }), [htmlWithIds])

  // F15：代码换行开关 → 根元素 data 标记（CSS 规则在 index.css；
  // off 保持横向滚动）。
  useEffect(() => {
    document.documentElement.dataset.codeWrap = codeWrap ? 'on' : 'off'
  }, [codeWrap])

  // 代码块复制按钮（pool #04）：渲染后 DOM 装饰（幂等），html 变化
  // （管线重跑）后重装饰。
  const contentRef = useRef<HTMLDivElement | null>(null)
  useEffect(() => {
    const container = contentRef.current
    if (container === null || !hasHtml) return
    decorateCodeCopyButtons(container)
  }, [htmlWithIds, hasHtml])

  // Reader 滚动容器 = .lumi-reader-article 的父级（结构契约见 Reader）。
  const getScrollContainer = (): HTMLElement | null =>
    contentRef.current?.closest('.lumi-reader-article')?.parentElement ?? null

  // F14/F16 渲染后装饰（幂等）：图片 zoom-in 标记 + 过宽表格展开按钮。
  // hidden 且未允许时不接线图片——无图可点，不偷偷加载。
  useEffect(() => {
    const container = contentRef.current
    if (container === null || !hasHtml) return
    if (imageMode !== 'hidden' || imagesAllowed) {
      for (const img of container.querySelectorAll<HTMLImageElement>('img')) {
        if (img.dataset.lumiLightboxReady === 'true') continue
        const src = img.getAttribute('src')
        if (src === null || src === '' || src.startsWith('data:')) continue
        img.dataset.lumiLightboxReady = 'true'
        img.tabIndex = -1
        img.style.cursor = 'zoom-in'
      }
    }
    for (const table of container.querySelectorAll('table')) {
      if (table.closest('[data-lumi-table-wrap]') !== null) continue
      // data-table-wide = 无布局环境（jsdom）的手动标记；有布局时按
      // 实测判定（超出 24px 才算过宽，防边框抖动误判）。
      const wide =
        table.hasAttribute('data-table-wide') ||
        table.scrollWidth > table.clientWidth + TABLE_WIDE_EXTRA_PX
      if (!wide) continue
      const wrap = container.ownerDocument.createElement('div')
      wrap.dataset.lumiTableWrap = 'true'
      wrap.className = 'lumi-table-wrap'
      table.parentNode?.insertBefore(wrap, table)
      wrap.appendChild(table)
      const button = container.ownerDocument.createElement('button')
      button.type = 'button'
      button.className = 'lumi-table-expand-btn'
      button.textContent = '展开查看'
      button.setAttribute('aria-label', '展开表格')
      button.dataset.lumiTableExpand = 'true'
      wrap.appendChild(button)
    }
  }, [htmlWithIds, hasHtml, imageMode, imagesAllowed])

  // F14/F16 事件委托：点击图片 → 灯箱；点击「展开查看」→ 表格面板。
  // 委托挂在容器上（容器节点跨 innerHTML 重渲染持久），装饰标记每次
  // 重装饰后依然成立。
  useEffect(() => {
    const container = contentRef.current
    if (container === null || !hasHtml) return
    const onClick = (event: MouseEvent) => {
      const target = event.target as HTMLElement | null
      if (target === null) return
      const expandButton = target.closest('[data-lumi-table-expand]')
      if (expandButton !== null) {
        const table = expandButton
          .closest('[data-lumi-table-wrap]')
          ?.querySelector('table')
        if (table !== null) {
          const scroller = getScrollContainer()
          savedScrollRef.current = scroller?.scrollTop ?? null
          setTablePanel({ table: table as HTMLTableElement })
          return
        }
      }
      const img = target.closest('img[data-lumi-lightbox-ready]') as HTMLImageElement | null
      if (img !== null) {
        const scroller = getScrollContainer()
        savedScrollRef.current = scroller?.scrollTop ?? null
        lastImageRef.current = img
        const all = Array.from(
          container.querySelectorAll<HTMLImageElement>('img[data-lumi-lightbox-ready]'),
        )
        setLightbox({
          images: all.map((el) => ({
            src: el.src,
            alt: el.getAttribute('alt') ?? '',
          })),
          index: Math.max(0, all.indexOf(img)),
        })
      }
    }
    container.addEventListener('click', onClick)
    return () => container.removeEventListener('click', onClick)
  }, [htmlWithIds, hasHtml])

  // F16：面板打开时把表格克隆进面板（cloneNode 保语义 table/th/td；
  // 面板内横向滚动，原表格不动）。
  useEffect(() => {
    if (tablePanel === null) return
    const host = tableHostRef.current
    if (host === null) return
    const clone = tablePanel.table.cloneNode(true) as HTMLTableElement
    clone.removeAttribute('data-table-wide')
    host.appendChild(clone)
    return () => {
      clone.remove()
    }
  }, [tablePanel])

  const closeLightbox = () => {
    setLightbox(null)
    restoreScrollAndFocus()
  }
  const closeTablePanel = () => {
    setTablePanel(null)
    restoreScrollAndFocus()
  }
  const restoreScrollAndFocus = () => {
    const scroller = getScrollContainer()
    if (scroller !== null && savedScrollRef.current !== null) {
      scroller.scrollTop = savedScrollRef.current
    }
    savedScrollRef.current = null
    // 焦点返回触发图片（图片装饰时已带 tabIndex=-1）。
    lastImageRef.current?.focus()
    lastImageRef.current = null
  }

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
          dangerouslySetInnerHTML={htmlProp}
        />
        {/* F14：图片灯箱（portal；焦点归还与滚动还原由本组件负责）。
            F16：表格展开面板（同一灯箱遮罩，内容模式）。lazy+Suspense：
            打开瞬间未加载完时渲染 null，随后自动出现。 */}
        <Suspense fallback={null}>
          <ArticleLightbox
            open={lightbox !== null}
            images={lightbox?.images}
            startIndex={lightbox?.index ?? 0}
            onClose={closeLightbox}
          />
        </Suspense>
        <Suspense fallback={null}>
          <ArticleLightbox
            open={tablePanel !== null}
            label="表格查看"
            onClose={closeTablePanel}
          >
            <div className="flex items-center justify-between border-b border-[var(--lumi-border)] px-4 py-2.5">
              <p className="text-sm font-medium text-[var(--lumi-text-primary)]">表格（可横向滚动）</p>
            </div>
            <div ref={tableHostRef} data-lumi-table-host="" className="overflow-auto p-4" />
          </ArticleLightbox>
        </Suspense>
      </>
    )
  }

  if (detail.contentText.trim() !== '') {
    return (
      <div className="article-content">
        <p className="whitespace-pre-wrap">{detail.contentText}</p>
        {/* F16 内容完整度：contentHtml 缺失 = 上游 feed 只给了摘要/文本，
            这是唯一可验证的信号——不凭长度猜测是否完整。
            （放在正文之后，保持 .article-content 首个 p 为正文的既有契约。） */}
        {!hasHtml ? (
          <p
            className="mt-3 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] px-2.5 py-1.5 text-xs text-[var(--lumi-text-secondary)]"
            data-lumi-content-completeness="summary-only"
          >
            上游 feed 未提供正文 HTML，本条仅显示可用的文本内容（可能是摘要）；
            完整性未知，可点「打开原文」核对。
          </p>
        ) : null}
      </div>
    )
  }

  return (
    <p className="article-content text-sm text-[var(--lumi-text-secondary)]">
      这篇文章没有可显示的正文。
    </p>
  )
}
