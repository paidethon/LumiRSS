import { lazy, Suspense, useEffect, useMemo, useRef, useState } from 'react'
import type { EntryDetail } from '../api/types'
import { renderArticleHtmlCached, sanitizeArticleHtmlCached } from '../lib/article-pipeline'
import 'katex/dist/katex.min.css'
import { readFootnoteDefinition } from '../lib/footnotes'
import { getEntryExtractPreview } from '../api/client'
import { Button } from './ui/Button'
import { useMutation } from '@tanstack/react-query'
import { deferImages } from '../lib/article-images'
import {
  blockRemoteImages,
  decorateBlockedRemoteImages,
} from '../lib/remote-images'
import { attachExternalLinkMenu, CleanLinkPreviewDialog } from './CleanLinkCopy'
import { WideTablePanel } from './WideTablePanel'
import {
  buildParaLink,
  paraStableId,
  takeParaTargetForEntry,
} from '../lib/para-anchor'
import { withHeadingIds } from '../lib/article-toc'
import { decorateCodeCopyButtons } from '../lib/code-copy'
import { TABLE_WIDE_EXTRA_PX } from '../lib/reader-tools'
import { useAppSettings } from '../store/app-settings'
import { prefersDarkScheme, resolveTheme } from '../lib/theme'
import ArticleToc from './ArticleToc'
import type { LightboxImage } from './ArticleLightbox'

// Bundle guard：灯箱只在点击图片/表格展开时可见——懒加载分包。
const ArticleLightbox = lazy(() => import('./ArticleLightbox'))

// ---- P05：段落「复制链接」图标按钮（渲染后 DOM 装饰，同 code-copy 模式） ----
// 图标取 lucide Link2 / Check / X 的 path（与 ReaderHeader 的 lucide-react
// 图标同一套形状，DOM 装饰场景内联 SVG 字符串）。反馈：成功图标变 ✓
// （强调色）+ aria-live「链接已复制」；失败图标变 ✕ + aria-live
// 「复制失败」——失败可见，不假装成功。~1.5s 后还原。
const PARA_LINK_FEEDBACK_MS = 1500

const PARA_LINK_SVG = (paths: string) =>
  `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">${paths}</svg>`

const ICON_LINK = PARA_LINK_SVG(
  '<path d="M9 17H7A5 5 0 0 1 7 7h2"/><path d="M15 7h2a5 5 0 1 1 0 10h-2"/><line x1="8" x2="16" y1="12" y2="12"/>',
)
const ICON_CHECK = PARA_LINK_SVG('<path d="M20 6 9 17l-5-5"/>')
const ICON_ERROR = PARA_LINK_SVG('<path d="M18 6 6 18"/><path d="m6 6 12 12"/>')

/** 构造段落复制链接按钮：纯图标（可访问名由 aria-label 提供，正文流
 * 中无文案）；点击复制 `${origin}/?entry=&para=` 段落链接，成功/失败
 * 反馈见上。readId 在点击时读取（装饰后段落 id 可能仍会被后续规则
 * 补写，取最新值）。 */
function createParaLinkButton(
  readId: () => string,
  entryRef: string,
): HTMLButtonElement {
  const button = document.createElement('button')
  button.type = 'button'
  button.className = 'lumi-para-link'
  button.setAttribute('aria-label', '复制段落链接')
  button.title = '复制段落链接'
  button.innerHTML =
    // aria-live 节点先于消息存在（可靠的播报）；文本由复制结果写入。
    `${ICON_LINK}<span class="sr-only" role="status" aria-live="polite"></span>`
  const status = button.querySelector('span[role="status"]')
  let revertTimer: number | undefined
  const showStatus = (state: 'copied' | 'error', icon: string, message: string) => {
    window.clearTimeout(revertTimer)
    button.dataset.state = state
    // 仅替换图标节点，保留 aria-live span（避免重建后播报丢失）。
    if (button.firstChild instanceof Element) button.firstChild.outerHTML = icon
    if (status !== null) status.textContent = message
    revertTimer = window.setTimeout(() => {
      button.dataset.state = ''
      if (button.firstChild instanceof Element) button.firstChild.outerHTML = ICON_LINK
      if (status !== null) status.textContent = ''
    }, PARA_LINK_FEEDBACK_MS)
  }
  button.addEventListener('click', () => {
    void navigator.clipboard
      .writeText(buildParaLink(window.location.origin, entryRef, readId()))
      .then(
        () => showStatus('copied', ICON_CHECK, '链接已复制'),
        () => showStatus('error', ICON_ERROR, '复制失败'),
      )
  })
  return button
}

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
  // F009：默认不加载远程图片（本地/快照资源不受影响；单图点击恢复）
  const blockRemote = useAppSettings((s) => s.settings.readerBlockRemoteImages)
  const [imagesAllowed, setImagesAllowed] = useState(false)
  useEffect(() => {
    setImagesAllowed(false)
  }, [detail.entryRef])

  // F14：图片灯箱状态；F16：表格展开面板状态。打开前保存滚动容器
  // scrollTop，关闭后还原（面板不改变正文阅读位置）。
  const [lightbox, setLightbox] = useState<{ images: LightboxImage[]; index: number } | null>(null)
  // F059：脚注弹层状态（Escape 关闭；「返回引用」滚动回触发标记）。
  const [footnotePopover, setFootnotePopover] = useState<{
    number: string
    html: string
    returnSeq: string
    anchor: HTMLElement
  } | null>(null)
  useEffect(() => {
    if (footnotePopover === null) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setFootnotePopover(null)
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [footnotePopover])
  const [tablePanel, setTablePanel] = useState<{ table: HTMLTableElement } | null>(null)
  const savedScrollRef = useRef<number | null>(null)
  const lastImageRef = useRef<HTMLImageElement | null>(null)

  // F048：web 策略失败徽标 + 未启用策略时的单篇「试读」（临时预览，不改来源策略）。
  const extractOnceMutation = useMutation({
    mutationFn: () => getEntryExtractPreview(detail.entryRef),
  })
  const showExtractBadge = detail.extractionFailed === true
  const rawHtml =
    extractOnceMutation.data?.contentHtml ?? detail.contentHtml ?? null
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
      footnotes: true,
      math: true,
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
      // F009：只拦截远程 http(s) 图（本地/快照/data:/blob: 原样保留）
      if (blockRemote) {
        const blocked = blockRemoteImages(withIds.html)
        return { html: blocked.html, toc: withIds.toc, deferredImageCount: 0 }
      }
      return { html: withIds.html, toc: withIds.toc, deferredImageCount: 0 }
    }
    const deferred = deferImages(withIds.html)
    return { html: deferred.html, toc: withIds.toc, deferredImageCount: deferred.imageCount }
  }, [html, hasHtml, imageMode, imagesAllowed, blockRemote])

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
    // F009：占位 img → 「加载本图」按钮（渲染后装饰，幂等）
    decorateBlockedRemoteImages(container)
    // F010：外链右键/长按菜单（复制链接 / 复制干净链接）
    const cleanupMenu = attachExternalLinkMenu(container, (url, x, y) => {
      setLinkMenu({ url, x, y })
    })
    return cleanupMenu
  }, [htmlWithIds, hasHtml])

  // F010：外链菜单与「复制干净链接」预览对话框状态
  const [linkMenu, setLinkMenu] = useState<{ url: string; x: number; y: number } | null>(null)
  const [cleanDialogUrl, setCleanDialogUrl] = useState<string | null>(null)
  useEffect(() => {
    if (linkMenu === null) return
    const close = () => setLinkMenu(null)
    window.addEventListener('click', close)
    window.addEventListener('scroll', close, true)
    return () => {
      window.removeEventListener('click', close)
      window.removeEventListener('scroll', close, true)
    }
  }, [linkMenu])

  // F015：段落定位缺失提示（诚实：正文变化 → 不跳错段）
  const [paraMissing, setParaMissing] = useState(false)

  // F015：段落 id 注入 + P05 hover/键盘悬显的「复制段落链接」图标按钮
  // 装饰（纯图标 + aria-label，文案不在正文流里；复制成功/失败以图标
  // 状态 + aria-live 即时反馈，见 .lumi-para-link CSS）；消费段落定位
  // 目标（滚动 + 2.5s 高亮；目标段落不存在 → 诚实提示，不跳错段）。
  useEffect(() => {
    const container = contentRef.current
    if (container === null || !hasHtml) return
    const paragraphs = Array.from(container.querySelectorAll(':scope > p'))
    paragraphs.forEach((p, index) => {
      const text = (p.textContent ?? '').trim()
      if (text === '') return
      if (!p.id) p.id = paraStableId(text, index)
      if (p.querySelector(':scope > button.lumi-para-link') !== null) return
      p.appendChild(createParaLinkButton(() => p.id, detail.entryRef))
    })
    const target = takeParaTargetForEntry(detail.entryRef)
    if (target !== null) {
      const el = container.querySelector(`#${CSS.escape(target)}`)
      if (el !== null) {
        el.scrollIntoView({ block: 'center' })
        el.classList.add('lumi-para-highlight')
        window.setTimeout(() => el.classList.remove('lumi-para-highlight'), 2500)
      } else {
        setParaMissing(true)
        window.setTimeout(() => setParaMissing(false), 3000)
      }
    }
  }, [htmlWithIds, hasHtml, detail.entryRef])

  // F026：摘要证据定位（ReaderSummary 点击句子 → 此处定位 + 高亮 2s；
  // 找不到由发起方显示诚实「未在原文定位」徽标，这里不做任何臆造）。
  useEffect(() => {
    const container = contentRef.current
    if (container === null || !hasHtml) return
    const handler = (event: Event) => {
      const detail = (event as CustomEvent).detail as { sentence?: string } | null
      const sentence = detail?.sentence
      if (typeof sentence !== 'string' || sentence === '') return
      import('../lib/locate-sentence').then(({ highlightSentenceInContainer }) => {
        highlightSentenceInContainer(container, sentence)
      }).catch(() => {})
    }
    document.addEventListener('lumi:locate-evidence', handler)
    return () => document.removeEventListener('lumi:locate-evidence', handler)
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
      // F059：脚注引用按钮 → 弹层显示净化后的定义内容。
      const fnButton = target.closest<HTMLElement>('[data-lumi-fn-ref]')
      if (fnButton !== null) {
        const key = fnButton.getAttribute('data-lumi-fn-key') ?? ''
        const number = fnButton.getAttribute('data-lumi-fn-ref') ?? ''
        const raw = readFootnoteDefinition(container, key)
        setFootnotePopover(
          raw === null
            ? null
            : {
                number,
                html: sanitizeArticleHtmlCached(raw),
                returnSeq: fnButton.getAttribute('data-lumi-fn-return') ?? '',
                anchor: fnButton,
              },
        )
        fnButton.focus()
        return
      }
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
        {/* F015：段落定位失败 → 诚实提示（不跳错段） */}
        {paraMissing && (
          <p
            role="status"
            data-testid="para-missing"
            className="mb-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2.5 py-1.5 text-xs text-[var(--lumi-text-secondary)]"
          >
            原文已变化，无法定位
          </p>
        )}
        <ArticleToc toc={toc} />
        {/* F048：提取失败诚实徽标 / 单篇「用提取正文试读」（不启用策略时临时预览） */}
        {(showExtractBadge || detail.extractPolicy !== 'web') && (
          <div className="mb-2 flex flex-wrap items-center gap-2 text-xs">
            {showExtractBadge && (
              <span role="status" className="rounded-[var(--lumi-radius-full)] bg-[var(--lumi-surface-selected)] px-2 py-0.5 text-[var(--lumi-text-secondary)]">
                提取失败，显示 RSS 正文
              </span>
            )}
            {detail.extractPolicy !== 'web' && (
              <Button size="sm" variant="ghost" disabled={extractOnceMutation.isPending} onClick={() => extractOnceMutation.mutate()}>
                {extractOnceMutation.isPending ? '提取中…' : '用提取正文试读'}
              </Button>
            )}
            {extractOnceMutation.data?.extractionFailed === true && (
              <span role="alert" className="text-[var(--lumi-danger)]">试读提取失败，仍显示 RSS 正文。</span>
            )}
          </div>
        )}
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
          {...(showExtractBadge ? { 'data-extract-failed': 'true' } : {})}
          ref={contentRef}
          className="article-content"
          // 注入的字符串永远是 DOMPurify 输出（唯一清洗点在
          // sanitize-article-html.ts；transforms 发生在 sanitize 之前；
          // withHeadingIds/deferImages 只在其上做属性级后处理）。
          dangerouslySetInnerHTML={htmlProp}
        />
        {/* F059：脚注弹层（净化后的定义内容；返回引用滚动回触发标记） */}
        {footnotePopover !== null && (
          <div
            role="dialog"
            aria-label={`脚注 ${footnotePopover.number}`}
            className="rounded-[var(--lumi-radius-md)] absolute z-30 max-w-sm border border-[var(--lumi-border)] bg-[var(--lumi-surface-elevated)] p-3 text-xs leading-relaxed shadow-lg"
            style={{
              left: Math.min(footnotePopover.anchor.getBoundingClientRect().left, 320),
            }}
          >
            <div
              className="footnote-body text-[var(--lumi-text-secondary)]"
              dangerouslySetInnerHTML={{ __html: footnotePopover.html }}
            />
            <div className="mt-2 flex items-center gap-2">
              <button
                type="button"
                className="text-[var(--lumi-accent)] hover:underline"
                onClick={() => {
                  const returnTarget = contentRef.current?.querySelector(
                    `[data-lumi-fn-return="${footnotePopover.returnSeq}"]`,
                  )
                  if (returnTarget instanceof HTMLElement) {
                    returnTarget.scrollIntoView({ block: 'center' })
                    returnTarget.focus()
                  }
                  setFootnotePopover(null)
                }}
              >
                返回引用
              </button>
              <button
                type="button"
                className="text-[var(--lumi-text-tertiary)] hover:text-[var(--lumi-text-primary)]"
                onClick={() => setFootnotePopover(null)}
              >
                关闭
              </button>
            </div>
          </div>
        )}
        {/* F010：外链右键/长按菜单（复制链接 / 复制干净链接） */}
        {linkMenu !== null && (
          <div
            role="menu"
            aria-label="链接操作"
            className="fixed z-[var(--lumi-z-dialog)] flex flex-col overflow-hidden rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface-elevated)] shadow-[var(--lumi-shadow-dialog)]"
            style={{ left: linkMenu.x, top: linkMenu.y }}
            onClick={(e) => e.stopPropagation()}
          >
            <button
              type="button"
              role="menuitem"
              className="min-h-11 px-3 py-2 text-left text-sm text-[var(--lumi-text-primary)] hover:bg-[var(--lumi-surface-hover)]"
              onClick={() => {
                void navigator.clipboard.writeText(linkMenu.url).catch(() => {})
                setLinkMenu(null)
              }}
            >
              复制链接
            </button>
            <button
              type="button"
              role="menuitem"
              data-testid="copy-clean-link"
              className="min-h-11 px-3 py-2 text-left text-sm text-[var(--lumi-text-primary)] hover:bg-[var(--lumi-surface-hover)]"
              onClick={() => {
                setCleanDialogUrl(linkMenu.url)
                setLinkMenu(null)
              }}
            >
              复制干净链接…
            </button>
          </div>
        )}
        <CleanLinkPreviewDialog
          open={cleanDialogUrl !== null}
          url={cleanDialogUrl}
          onClose={() => setCleanDialogUrl(null)}
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
            {tablePanel !== null && <WideTablePanel table={tablePanel.table} />}
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
