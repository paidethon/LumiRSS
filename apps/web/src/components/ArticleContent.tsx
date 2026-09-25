import { lazy, Suspense, useEffect, useMemo, useRef, useState } from 'react'
import type { EntryDetail } from '../api/types'
import { renderArticleHtmlCached, sanitizeArticleHtmlCached } from '../lib/article-pipeline'
import 'katex/dist/katex.min.css'
import { readFootnoteDefinition } from '../lib/footnotes'
import { getEntryExtractPreview } from '../api/client'
import { Button } from './ui/Button'
import { cx as cxRaw } from './ui/cx'
import { useMutation } from '@tanstack/react-query'
import { deferImages } from '../lib/article-images'
import {
  blockRemoteImages,
  decorateBlockedRemoteImages,
} from '../lib/remote-images'
import {
  decorateManualMedia,
  deferMedia,
  mediaPolicyFor,
  writeMediaPolicy,
  type MediaPolicyMode,
} from '../lib/media-policy'
import { attachExternalLinkMenu, CleanLinkPreviewDialog } from './CleanLinkCopy'
import { WideTablePanel } from './WideTablePanel'
import { CodeReaderPanel } from './CodeReaderPanel'
import { Dialog } from './ui/Dialog'
import { safeExternalHttpUrl } from '../lib/safe-external-http-url'
import {
  buildParaLink,
  paraStableId,
  takeParaTargetForEntry,
} from '../lib/para-anchor'
import { withHeadingIds } from '../lib/article-toc'
import { decorateCodeCopyButtons } from '../lib/code-copy'
import { countCodeLines, CODE_READER_MIN_LINES } from '../lib/code-reader'
import { renderMath } from '../lib/katex-render'
import {
  captureAnchorText,
  findAnchorElement,
} from '../lib/reading-position'
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

/** N060：滚动锚点候选（与 lib/reading-position findAnchorElement、
 * Reader 的保存选择器同一族元素；文档序取视口顶线上方最近者）。 */
const ANCHOR_SELECTOR = [
  'p',
  'li',
  'pre',
  'blockquote',
  'h1',
  'h2',
  'h3',
  'h4',
  'h5',
  'h6',
]
  .map((tag) => `.lumi-reader-article ${tag}`)
  .join(', ')

/** N060：视口顶判定线（与 Reader 保存逻辑一致：top 80px 线上方最近块）。 */
const ANCHOR_VIEWPORT_OFFSET_PX = 80

/** N060：标题候选（最近标题降级用；h1–h6 全算标题）。 */
const HEADING_SELECTOR = ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']
  .map((tag) => `.lumi-reader-article ${tag}`)
  .join(', ')

const PARA_LINK_SVG = (paths: string) =>
  `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">${paths}</svg>`

const ICON_LINK = PARA_LINK_SVG(
  '<path d="M9 17H7A5 5 0 0 1 7 7h2"/><path d="M15 7h2a5 5 0 1 1 0 10h-2"/><line x1="8" x2="16" y1="12" y2="12"/>',
)
const ICON_CHECK = PARA_LINK_SVG('<path d="M20 6 9 17l-5-5"/>')
const ICON_ERROR = PARA_LINK_SVG('<path d="M18 6 6 18"/><path d="m6 6 12 12"/>')
// N057：展开代码（lucide maximize-2 同形；DOM 装饰场景内联 SVG，
// 同段落链接按钮的既定例外模式）。
const ICON_CODE_EXPAND = PARA_LINK_SVG(
  '<polyline points="15 3 21 3 21 9"/><polyline points="9 21 3 21 3 15"/><line x1="21" x2="14" y1="3" y2="10"/><line x1="3" x2="10" y1="21" y2="14"/>',
)

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

/** N062：图片说明提取——最近 figure 的 figcaption 文本，否则 img 的
 * title 属性，否则 aria-label；都没有 → null（灯箱明示「未提供说明」，
 * 不拿 alt 冒充说明）。连续空白规范化。 */
export function extractImageCaption(img: HTMLImageElement): string | null {
  const figcaption = img.closest('figure')?.querySelector('figcaption')?.textContent
  const candidates = [
    figcaption ?? '',
    img.getAttribute('title') ?? '',
    img.getAttribute('aria-label') ?? '',
  ]
  for (const candidate of candidates) {
    const text = candidate.replace(/\s+/g, ' ').trim()
    if (text !== '') return text
  }
  return null
}

/** N062：图片来源主机名（img.src 属性经浏览器解析为绝对地址；data:/
 * 相对失败等取不到 → null，灯箱显示「来源未知」）。 */
export function extractImageHost(img: HTMLImageElement): string | null {
  try {
    return new URL(img.src).hostname !== '' ? new URL(img.src).hostname : null
  } catch {
    return null
  }
}

/** N064：公式专注视图（ArticleContent 文件内的内部组件——katex 输出
 * 先过唯一净化点 sanitizeArticleHtmlCached 再进 dangerouslySetInnerHTML，
 * 与脚注弹层同模式；更大的展示字号由 .lumi-formula-focus 提供）。
 * 「复制 LaTeX」复制的是渲染管线的 TeX 原文（data-lumi-tex）；
 * 渲染失败诚实显示（可复制源码，不假装成功）。 */
function FormulaFocusView({ tex, display }: { tex: string; display: boolean }) {
  const [html, setHtml] = useState<string | null>(null)
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    let cancelled = false
    setHtml(null)
    setFailed(false)
    void renderMath(tex, display).then((out) => {
      if (cancelled) return
      if (out === null) {
        setFailed(true)
        return
      }
      setHtml(sanitizeArticleHtmlCached(out))
    })
    return () => {
      cancelled = true
    }
  }, [tex, display])
  const [feedback, setFeedback] = useState<string | null>(null)
  async function copyLaTeX() {
    try {
      await navigator.clipboard.writeText(tex)
      setFeedback('已复制 LaTeX')
    } catch {
      setFeedback('复制失败：请检查剪贴板权限')
    }
    window.setTimeout(() => setFeedback(null), 2000)
  }
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div
        className="flex items-center gap-2 border-b border-[var(--lumi-border)] px-4 py-2"
        data-testid="formula-toolbar"
      >
        <span className="text-sm font-medium text-[var(--lumi-text-primary)]">公式</span>
        <span className="flex-1" />
        {feedback !== null && (
          <span role="status" className="text-xs text-[var(--lumi-accent-text)]">
            {feedback}
          </span>
        )}
        <Button size="sm" variant="secondary" onClick={() => void copyLaTeX()}>
          复制 LaTeX
        </Button>
      </div>
      <div data-testid="formula-view" className="min-h-0 flex-1 overflow-auto p-6">
        {failed ? (
          <p className="text-sm text-[var(--lumi-text-secondary)]">
            公式渲染失败，可用「复制 LaTeX」取得源码。
          </p>
        ) : html === null ? (
          <p className="text-sm text-[var(--lumi-text-secondary)]" role="status">
            公式渲染中…
          </p>
        ) : (
          <div className="lumi-formula-focus" dangerouslySetInnerHTML={{ __html: html }} />
        )}
      </div>
    </div>
  )
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
  // N066：按源媒体策略（设备本地 localStorage 映射；'manual' = 图片/视频/
  // 音频一律先占位，点击才加载单个元素——初始渲染零外部媒体请求）。
  const [mediaPolicy, setMediaPolicyState] = useState<MediaPolicyMode>(() =>
    mediaPolicyFor(detail.feedUrl),
  )
  useEffect(() => {
    setMediaPolicyState(mediaPolicyFor(detail.feedUrl))
  }, [detail.feedUrl, detail.entryRef])
  const manualMedia = mediaPolicy === 'manual'
  const setMediaPolicy = (mode: MediaPolicyMode) => {
    if (detail.feedUrl !== null && detail.feedUrl !== undefined) {
      writeMediaPolicy(detail.feedUrl, mode)
    }
    setMediaPolicyState(mode)
  }
  // F070：首图破格（管线给首图打 data 标记，CSS 消费满宽）
  const firstImageFullBleed = useAppSettings((s) => s.settings.readerFirstImageFullBleed)
  // F073：代码块行号（管线按行包 span + CSS counter；与高亮/换行共存）
  const codeLineNumbers = useAppSettings((s) => s.settings.readerCodeLineNumbers)
  // F079：清理 position:fixed/sticky 非内容元素（transform 层；DOMPurify
  // 仍是最终边界——本 transform 只删除元素，不引入任何新标记）
  const stripFixedMedia = useAppSettings((s) => s.settings.readerStripFixedMedia)
  const [imagesAllowed, setImagesAllowed] = useState(false)
  useEffect(() => {
    setImagesAllowed(false)
  }, [detail.entryRef])

  // N032：内容丢失恢复选择（当前 / 上次完整版本）。切换只改渲染源，
  // 两种版本都走同一条 sanitize 管线（DOMPurify 唯一清洗点不变）。
  // 状态把 entryRef 一并存入：换文章时渲染期直接归位「当前」，
  // 无需 effect（换 entryRef 即自动失效）。
  const [variantState, setVariantState] = useState<{
    ref: string
    kind: 'current' | 'last_known_full'
  }>({ ref: detail.entryRef, kind: 'current' })
  const variant: 'current' | 'last_known_full' =
    variantState.ref === detail.entryRef ? variantState.kind : 'current'
  const setVariant = (kind: 'current' | 'last_known_full') =>
    setVariantState({ ref: detail.entryRef, kind })
  // N060：切换前记录当前视口锚点（段落文本前缀 + 滚动比例），新内容
  // 渲染完成后由下方 effect 重锚定。绝不触碰已读状态。
  const captureSwitchAnchor = (): { anchorText: string | null; ratio: number } | null => {
    const scroller = getScrollContainer()
    if (scroller === null) return null
    const max = scroller.scrollHeight - scroller.clientHeight
    const ratio = max > 0 ? Math.min(1, Math.max(0, scroller.scrollTop / max)) : 0
    const containerTop = scroller.getBoundingClientRect().top
    let anchor: Element | null = null
    for (const el of scroller.querySelectorAll(ANCHOR_SELECTOR)) {
      if (el.getBoundingClientRect().top > containerTop + ANCHOR_VIEWPORT_OFFSET_PX) break
      anchor = el
    }
    return { anchorText: captureAnchorText(anchor), ratio }
  }
  const switchVariant = (kind: 'current' | 'last_known_full') => {
    pendingAnchorRef.current = captureSwitchAnchor()
    setVariant(kind)
  }

  // F14：图片灯箱状态；F16：表格展开面板状态。打开前保存滚动容器
  // scrollTop，关闭后还原（面板不改变正文阅读位置）。
  // N061：sources 保存灯箱各图对应的正文源 img（「在原文中查看」定位用）。
  const [lightbox, setLightbox] = useState<{
    images: LightboxImage[]
    index: number
    sources: HTMLImageElement[]
  } | null>(null)
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
  // N057：代码独立阅读页状态；N064：公式专注视图状态（同一灯箱遮罩，
  // 内容模式）。打开前保存滚动位置，关闭后还原。
  const [codePanel, setCodePanel] = useState<{ pre: HTMLPreElement } | null>(null)
  const [formulaPanel, setFormulaPanel] = useState<{ tex: string; display: boolean } | null>(null)
  const savedScrollRef = useRef<number | null>(null)
  // 关闭后的焦点归还目标（触发元素：图片 / 展开按钮 / 公式 span）。
  const focusReturnRef = useRef<HTMLElement | null>(null)
  // N060：内容版本切换重锚定——切换时刻记录（锚点文本 + 滚动比例），
  // 新内容渲染完成后消费（见下方 effect）。
  const pendingAnchorRef = useRef<{ anchorText: string | null; ratio: number } | null>(null)
  const [anchorNotice, setAnchorNotice] = useState(false)
  const anchorNoticeTimerRef = useRef<number | undefined>(undefined)

  // F048：web 策略失败徽标 + 未启用策略时的单篇「试读」（临时预览，不改来源策略）。
  const extractOnceMutation = useMutation({
    mutationFn: () => getEntryExtractPreview(detail.entryRef),
  })
  // F078：重新抓取原文快照并排对比（复用既有 extractOnce 安全抓取通道；
  // 独立 mutation，不污染 F048 试读状态）。
  const compareExtractMutation = useMutation({
    mutationFn: () => getEntryExtractPreview(detail.entryRef),
  })
  const [compareOpen, setCompareOpen] = useState(false)
  const compareAvailable = safeExternalHttpUrl(detail.url) !== null
  const openCompare = () => {
    setCompareOpen(true)
    compareExtractMutation.mutate()
  }
  const showExtractBadge = detail.extractionFailed === true
  // N032：last_known_full 只在该版本真实保留时出现（BFF 诚实缺席）。
  const lastFullVariant =
    detail.contentVariants?.variants?.find((v) => v.kind === 'last_known_full') ?? null
  const lastFullVariantHtml =
    variant === 'last_known_full' ? (lastFullVariant?.contentHtml ?? null) : null
  const rawHtml =
    extractOnceMutation.data?.contentHtml ?? lastFullVariantHtml ?? detail.contentHtml ?? null
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
      firstImageFullBleed,
      codeLineNumbers,
      stripFixedMedia,
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
    firstImageFullBleed,
    codeLineNumbers,
    stripFixedMedia,
  ])

  // 目录提取（pool #03）：在 DOMPurify 输出之上给 h2–h4 注入确定性 id
  // 并生成目录；输入已清洗，注入的只有 id 属性，无脚本注入面。
  // F22：hidden 且未单篇覆盖 → 摘除图片地址（不发请求），并统计数量；
  // 覆盖后 memo 重算，直接产回带 src 的版本（defer 结果不回写状态）。
  // N066：仅手动策略在 F22/F009 之后追加 deferMedia（img 已被摘除则
  // 自然跳过；video/audio/poster/source/track 在此摘除），幂等。
  const { html: htmlWithIds, toc, deferredImageCount, manualMediaCount } = useMemo(() => {
    if (!hasHtml || html === '') {
      return { html, toc: [], deferredImageCount: 0, manualMediaCount: 0 }
    }
    const withIds = withHeadingIds(html)
    let out = withIds.html
    let deferredImageCount = 0
    let manualMediaCount = 0
    if (imageMode === 'hidden' && !imagesAllowed) {
      const deferred = deferImages(out)
      out = deferred.html
      deferredImageCount = deferred.imageCount
    } else if (blockRemote) {
      // F009：只拦截远程 http(s) 图（本地/快照/data:/blob: 原样保留）
      out = blockRemoteImages(out).html
    }
    if (manualMedia) {
      const media = deferMedia(out)
      out = media.html
      manualMediaCount = media.mediaCount
    }
    return { html: out, toc: withIds.toc, deferredImageCount, manualMediaCount }
  }, [html, hasHtml, imageMode, imagesAllowed, blockRemote, manualMedia])

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
    // N066：仅手动媒体 → 「加载图片/视频/音频」占位按钮（幂等）
    decorateManualMedia(container)
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
        // N051：章节模式（ArticleToc）先切到包含该段的章节，随后定位
        // 才可见可滚（隐藏块 scrollIntoView 无效）。
        document.dispatchEvent(
          new CustomEvent('lumi:para-navigate', { detail: { element: el } }),
        )
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

  // N060：内容版本切换后的重锚定。管线是异步的：pendingAnchorRef 在
  // 切换时刻记录（captureSwitchAnchor），htmlWithIds 更新（新内容已入
  // DOM）后在此消费——findAnchorElement 命中原段落/标题 → 回到原位；
  // 匹配失败 → 按切换前滚动比例在标题序列上取最近的标题（内容高度已
  // 变化，几何位置不可比，文档序比例取点是可解释的诚实近似；最坏也只
  // 落在最后一个标题，绝不落到文末）+ 诚实提示；全文无标题 → 回到顶部
  // （同样绝不到文末），不显示虚假的「已定位」文案。整个流程只写
  // scrollTop，绝不触碰已读状态。
  useEffect(() => {
    const pending = pendingAnchorRef.current
    if (pending === null) return
    pendingAnchorRef.current = null
    const scroller = getScrollContainer()
    if (scroller === null) return
    const anchor =
      pending.anchorText !== null ? findAnchorElement(scroller, pending.anchorText) : null
    if (anchor !== null) {
      const top =
        anchor.getBoundingClientRect().top -
        scroller.getBoundingClientRect().top +
        scroller.scrollTop
      scroller.scrollTop = Math.max(0, top - 12)
      return
    }
    const headings = Array.from(scroller.querySelectorAll(HEADING_SELECTOR))
    if (headings.length > 0) {
      const index = Math.min(
        headings.length - 1,
        Math.floor(pending.ratio * headings.length),
      )
      const target = headings[index] as HTMLElement
      const top =
        target.getBoundingClientRect().top -
        scroller.getBoundingClientRect().top +
        scroller.scrollTop
      scroller.scrollTop = Math.max(0, top - 12)
      setAnchorNotice(true)
      window.clearTimeout(anchorNoticeTimerRef.current)
      anchorNoticeTimerRef.current = window.setTimeout(() => setAnchorNotice(false), 3500)
    } else {
      scroller.scrollTop = 0
    }
  }, [htmlWithIds])

  // N060：提取试读失败时渲染源不变——作废挂起的重锚定（诚实地不跳）。
  useEffect(() => {
    if (extractOnceMutation.isError) pendingAnchorRef.current = null
  }, [extractOnceMutation.isError])

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
    // N057：长代码块（> 20 行）出现「展开代码」图标入口（同表格展开的
    // DOM 装饰模式，幂等）；点击经下方事件委托打开独立阅读页。
    for (const pre of container.querySelectorAll('pre')) {
      if (pre.querySelector('[data-lumi-code-expand]') !== null) continue
      const text = (pre.querySelector('code') ?? pre).textContent ?? ''
      if (countCodeLines(text) <= CODE_READER_MIN_LINES) continue
      const button = container.ownerDocument.createElement('button')
      button.type = 'button'
      button.className = 'lumi-code-expand-btn'
      button.dataset.lumiCodeExpand = 'true'
      button.setAttribute('aria-label', '展开代码')
      button.title = '展开代码'
      button.innerHTML = ICON_CODE_EXPAND
      pre.appendChild(button)
    }
    // N064：公式专注视图接线（渲染后装饰，幂等）。只有带 data-lumi-tex
    // （管线渲染、持有 TeX 原文）的公式可交互——上游自带 KaTeX HTML 无
    // 原文可复制重渲，诚实不提供放大入口。
    for (const el of container.querySelectorAll<HTMLElement>('span[data-lumi-tex]')) {
      if (el.dataset.lumiFormulaReady === 'true') continue
      el.dataset.lumiFormulaReady = 'true'
      el.tabIndex = 0
      el.setAttribute('role', 'button')
      el.setAttribute('aria-label', '放大公式')
    }
  }, [htmlWithIds, hasHtml, imageMode, imagesAllowed])

  // N064：公式专注视图打开（点击 + 键盘 Enter/Space 同一入口）。
  // 无 TeX 原文（data-lumi-tex 缺失/空白）→ 不开面板，诚实不假装。
  const openFormulaPanel = (el: Element): void => {
    const tex = el.getAttribute('data-lumi-tex') ?? ''
    if (tex.trim() === '') return
    const scroller = getScrollContainer()
    savedScrollRef.current = scroller?.scrollTop ?? null
    focusReturnRef.current = el instanceof HTMLElement ? el : null
    setFormulaPanel({ tex, display: el.querySelector('.katex-display') !== null })
  }

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
          focusReturnRef.current = expandButton as HTMLElement
          setTablePanel({ table: table as HTMLTableElement })
          return
        }
      }
      // N057：展开代码 → 独立阅读页（同一灯箱遮罩，内容模式）。
      const codeExpandButton = target.closest('[data-lumi-code-expand]')
      if (codeExpandButton !== null) {
        const pre = codeExpandButton.closest('pre')
        if (pre !== null) {
          const scroller = getScrollContainer()
          savedScrollRef.current = scroller?.scrollTop ?? null
          focusReturnRef.current = codeExpandButton as HTMLElement
          setCodePanel({ pre: pre as HTMLPreElement })
          return
        }
      }
      // N064：公式专注视图（有 TeX 原文才可开——诚实降级）。
      const formulaEl = target.closest('[data-lumi-formula-ready]')
      if (formulaEl !== null) {
        openFormulaPanel(formulaEl)
        return
      }
      const img = target.closest('img[data-lumi-lightbox-ready]') as HTMLImageElement | null
      if (img !== null) {
        const scroller = getScrollContainer()
        savedScrollRef.current = scroller?.scrollTop ?? null
        focusReturnRef.current = img
        const all = Array.from(
          container.querySelectorAll<HTMLImageElement>('img[data-lumi-lightbox-ready]'),
        )
        setLightbox({
          images: all.map((el) => ({
            src: el.src,
            alt: el.getAttribute('alt') ?? '',
            caption: extractImageCaption(el),
            host: extractImageHost(el),
          })),
          index: Math.max(0, all.indexOf(img)),
          sources: all,
        })
      }
    }
    container.addEventListener('click', onClick)
    return () => container.removeEventListener('click', onClick)
  }, [htmlWithIds, hasHtml])

  useEffect(() => {
    const container = contentRef.current
    if (container === null || !hasHtml) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Enter' && event.key !== ' ') return
      const target = event.target as Element | null
      const el = target?.closest?.('[data-lumi-formula-ready]') ?? null
      if (el !== null && target instanceof HTMLElement) {
        event.preventDefault()
        openFormulaPanel(el)
      }
    }
    container.addEventListener('keydown', onKey)
    return () => container.removeEventListener('keydown', onKey)
  }, [htmlWithIds, hasHtml])



  const closeLightbox = () => {
    setLightbox(null)
    restoreScrollAndFocus()
  }
  const closeTablePanel = () => {
    setTablePanel(null)
    restoreScrollAndFocus()
  }
  // N057/N064：代码阅读页 / 公式专注视图关闭——与表格面板同一还原语义
  //（滚动位置复原 + 焦点归还触发元素）。
  const closeCodePanel = () => {
    setCodePanel(null)
    restoreScrollAndFocus()
  }
  const closeFormulaPanel = () => {
    setFormulaPanel(null)
    restoreScrollAndFocus()
  }
  // N061：在原文中查看——关闭灯箱后滚动到正文源图（定位滚动取代
  // 「回到打开前位置」，savedScroll 作废防陈旧还原），焦点随源图。
  const locateImageInArticle = (index: number) => {
    const source = lightbox?.sources[index] ?? null
    setLightbox(null)
    savedScrollRef.current = null
    focusReturnRef.current = null
    if (source !== null) {
      source.scrollIntoView({ block: 'center' })
      source.focus()
    }
  }
  const restoreScrollAndFocus = () => {
    const scroller = getScrollContainer()
    if (scroller !== null && savedScrollRef.current !== null) {
      scroller.scrollTop = savedScrollRef.current
    }
    savedScrollRef.current = null
    // 焦点返回触发元素（图片装饰时已带 tabIndex=-1；展开按钮/公式
    // span 各自带可聚焦语义）。
    focusReturnRef.current?.focus()
    focusReturnRef.current = null
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
        {/* N060：版本切换重锚定失败 → 最近标题降级的诚实提示 */}
        {anchorNotice && (
          <p
            role="status"
            data-testid="anchor-notice"
            className="mb-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2.5 py-1.5 text-xs text-[var(--lumi-text-secondary)]"
          >
            已定位到最近标题
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
              <Button
                size="sm"
                variant="ghost"
                disabled={extractOnceMutation.isPending}
                onClick={() => {
                  // N060：提取试读也是内容源切换——同样重锚定。
                  pendingAnchorRef.current = captureSwitchAnchor()
                  extractOnceMutation.mutate()
                }}
              >
                {extractOnceMutation.isPending ? '提取中…' : '用提取正文试读'}
              </Button>
            )}
            {extractOnceMutation.data?.extractionFailed === true && (
              <span role="alert" className="text-[var(--lumi-danger)]">试读提取失败，仍显示 RSS 正文。</span>
            )}
          </div>
        )}
        {/* N032：当前正文明显变短 → 版本选择条（诚实标注两个选项）。
            web 提取策略下正文来自文章页提取，与上游 RSS 交付无关，不显示。 */}
        {detail.contentVariants?.triggered && detail.extractPolicy !== 'web' && (
          <div
            role="note"
            data-testid="content-variants-bar"
            className="mb-2 flex flex-wrap items-center gap-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] px-2.5 py-1.5 text-xs text-[var(--lumi-text-secondary)]"
          >
            <span>当前正文明显变短</span>
            <div role="group" aria-label="选择正文版本" className="flex items-center gap-1">
              <button
                type="button"
                aria-pressed={variant === 'current'}
                onClick={() => switchVariant('current')}
                className={cxRaw(
                  'min-h-7 rounded-[var(--lumi-radius-full)] px-2 py-0.5 transition-colors duration-[var(--lumi-motion-fast)]',
                  'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
                  variant === 'current'
                    ? 'bg-[var(--lumi-accent-soft)] text-[var(--lumi-accent-text)]'
                    : 'text-[var(--lumi-text-tertiary)] hover:text-[var(--lumi-text-secondary)]',
                )}
              >
                当前
              </button>
              {lastFullVariant !== null && (
                <button
                  type="button"
                data-testid="variant-last-full"
                aria-pressed={variant === 'last_known_full'}
                onClick={() => switchVariant('last_known_full')}
                  className={cxRaw(
                    'min-h-7 rounded-[var(--lumi-radius-full)] px-2 py-0.5 transition-colors duration-[var(--lumi-motion-fast)]',
                    'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
                    variant === 'last_known_full'
                      ? 'bg-[var(--lumi-accent-soft)] text-[var(--lumi-accent-text)]'
                      : 'text-[var(--lumi-text-tertiary)] hover:text-[var(--lumi-text-secondary)]',
                  )}
                >
                  上次完整版本
                  {lastFullVariant.capturedAt ? `（${lastFullVariant.capturedAt.slice(0, 10)}）` : ''}
                </button>
              )}
            </div>
          </div>
        )}
        {/* N066：本源媒体加载策略（设备本地，按 feedUrl 记忆）。
            仅手动 = 图片/视频/音频先占位，点击才加载单个元素。 */}
        {detail.feedUrl !== null && detail.feedUrl !== undefined && detail.feedUrl !== '' && (
          <div
            data-testid="media-policy-bar"
            className="mb-2 flex flex-wrap items-center gap-2 text-xs text-[var(--lumi-text-secondary)]"
          >
            <span>媒体加载（本源）</span>
            <div
              role="group"
              aria-label="本源媒体加载策略"
              className="inline-flex gap-0.5 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-0.5"
            >
              <button
                type="button"
                aria-pressed={!manualMedia}
                data-testid="media-policy-default"
                onClick={() => setMediaPolicy('default')}
                className={cxRaw(
                  'min-h-7 rounded-[var(--lumi-radius-sm)] px-2 py-0.5 transition-colors duration-[var(--lumi-motion-fast)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
                  manualMedia
                    ? 'text-[var(--lumi-text-tertiary)] hover:text-[var(--lumi-text-secondary)]'
                    : 'bg-[var(--lumi-surface-selected)] text-[var(--lumi-text-primary)]',
                )}
              >
                默认
              </button>
              <button
                type="button"
                aria-pressed={manualMedia}
                data-testid="media-policy-manual"
                onClick={() => setMediaPolicy('manual')}
                className={cxRaw(
                  'min-h-7 rounded-[var(--lumi-radius-sm)] px-2 py-0.5 transition-colors duration-[var(--lumi-motion-fast)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
                  manualMedia
                    ? 'bg-[var(--lumi-surface-selected)] text-[var(--lumi-text-primary)]'
                    : 'text-[var(--lumi-text-tertiary)] hover:text-[var(--lumi-text-secondary)]',
                )}
              >
                仅手动
              </button>
            </div>
            {manualMedia && manualMediaCount > 0 && (
              <span data-testid="manual-media-count">
                仅手动：{manualMediaCount} 个媒体元素待点击加载
              </span>
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
        {/* F078：重新抓取原文快照并排对比入口（url 可信才提供；
            抓取走服务端既有 SSRF 安全通道，此处只展示结果） */}
        {compareAvailable && (
          <div className="mb-2 flex flex-wrap items-center gap-2 text-xs">
            <Button
              size="sm"
              variant="ghost"
              data-testid="extract-compare-open"
              disabled={compareExtractMutation.isPending}
              onClick={openCompare}
            >
              {compareExtractMutation.isPending ? '抓取原文中…' : '与重抓原文对比'}
            </Button>
          </div>
        )}
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
        {/* F078：并排对比对话框（左=当前正文，右=重抓原文快照；
            窄屏退化为上下堆叠；两列内容都是 DOMPurify 输出） */}
        <Dialog
          open={compareOpen}
          onClose={() => setCompareOpen(false)}
          title="正文 vs 重抓原文"
          footer={
            <Button variant="secondary" onClick={() => setCompareOpen(false)}>
              关闭
            </Button>
          }
        >
          <div className="grid max-h-[70vh] gap-3 overflow-y-auto md:grid-cols-2">
            <section data-testid="extract-compare-current" className="min-w-0">
              <h3 className="mb-1.5 text-xs font-medium text-[var(--lumi-text-secondary)]">
                当前正文
              </h3>
              <div className="article-content text-sm" dangerouslySetInnerHTML={htmlProp} />
            </section>
            <section data-testid="extract-compare-refetch" className="min-w-0">
              <h3 className="mb-1.5 text-xs font-medium text-[var(--lumi-text-secondary)]">
                重抓原文
              </h3>
              {compareExtractMutation.isPending ? (
                <p className="text-sm text-[var(--lumi-text-secondary)]">抓取中…</p>
              ) : compareExtractMutation.isError ? (
                <p role="alert" className="text-sm text-[var(--lumi-danger)]">
                  重新抓取失败：{compareExtractMutation.error instanceof Error ? compareExtractMutation.error.message : '请稍后重试。'}
                </p>
              ) : compareExtractMutation.data?.extractionFailed === true ? (
                <p role="alert" className="text-sm text-[var(--lumi-danger)]">
                  原文抓取失败，无法对比。
                </p>
              ) : compareExtractMutation.data?.contentHtml ? (
                <div
                  className="article-content text-sm"
                  dangerouslySetInnerHTML={{
                    __html: sanitizeArticleHtmlCached(compareExtractMutation.data.contentHtml),
                  }}
                />
              ) : (
                <p className="text-sm text-[var(--lumi-text-secondary)]">
                  原文没有可显示的正文。
                </p>
              )}
            </section>
          </div>
        </Dialog>
        {/* F14：图片灯箱（portal；焦点归还与滚动还原由本组件负责）。
            F16：表格展开面板（同一灯箱遮罩，内容模式）。lazy+Suspense：
            打开瞬间未加载完时渲染 null，随后自动出现。
            N061：onLocate 接「在原文中查看」。 */}
        <Suspense fallback={null}>
          <ArticleLightbox
            open={lightbox !== null}
            images={lightbox?.images}
            startIndex={lightbox?.index ?? 0}
            onLocate={locateImageInArticle}
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
        {/* N057：代码块独立阅读页（同一灯箱遮罩，内容模式；关闭还原
            滚动位置 + 焦点归还「展开代码」按钮）。 */}
        <Suspense fallback={null}>
          <ArticleLightbox
            open={codePanel !== null}
            label="代码查看"
            onClose={closeCodePanel}
          >
            {codePanel !== null && <CodeReaderPanel pre={codePanel.pre} />}
          </ArticleLightbox>
        </Suspense>
        {/* N064：公式专注视图（同一灯箱遮罩，内容模式）。 */}
        <Suspense fallback={null}>
          <ArticleLightbox
            open={formulaPanel !== null}
            label="公式查看"
            onClose={closeFormulaPanel}
          >
            {formulaPanel !== null && (
              <FormulaFocusView tex={formulaPanel.tex} display={formulaPanel.display} />
            )}
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
