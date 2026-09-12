import { useState } from 'react'
import { Camera, Check, Clock, ExternalLink, Languages, Loader2, MessageSquare, Star } from 'lucide-react'
import type { EntryDetail } from '../api/types'
import { useAiSettings, useCreateSnapshotMutation, useEntryStateMutation } from '../api/queries'
import { useToggleReadLater } from '../lib/read-later'
import { safeExternalHttpUrl } from '../lib/safe-external-http-url'
import { formatReadingTime, textFromHtml } from '../lib/reading-time'
import { dateTimeFormatter as dateFormatter } from '../lib/date-format'
import { localTranslatorAvailable } from '../lib/local-translator'
import { useAppSettings } from '../store/app-settings'
import ReaderAaPanel from './ReaderAaPanel'
import type { ReaderViewMode } from '../lib/translation-blocks'
import { IconButton } from './ui/IconButton'
import { Menu } from './ui/Menu'
import { Tooltip } from './ui/Tooltip'
import { cx } from './ui/cx'

function formatPublishedAt(value: string | null | undefined): string {
  if (value == null) {
    return ''
  }
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '' : dateFormatter.format(date)
}

/** phase2 Gate 3：保存快照（monolith 离线快照；仅绝对 http/https 原文
 * 可保存——由父级以 safeExternalHttpUrl 过滤后条件渲染）。
 * 成功短暂显示「快照已保存」；失败原样透出 BFF message
 *（monolith_unavailable / 配额超限等，诚实语义）。 */
function SaveSnapshotButton({ url }: { url: string }) {
  const [savedRecently, setSavedRecently] = useState(false)
  const createSnapshot = useCreateSnapshotMutation()

  const failure =
    createSnapshot.isError && createSnapshot.error instanceof Error
      ? createSnapshot.error.message
      : createSnapshot.isError
        ? '快照保存失败，请稍后重试。'
        : null
  const tooltip = failure ?? (savedRecently ? '快照已保存' : '保存快照')

  return (
    <Tooltip content={tooltip}>
      <IconButton
        icon={
          createSnapshot.isPending ? (
            <Loader2 aria-hidden className="animate-spin" />
          ) : (
            <Camera
              aria-hidden
              className={cx(
                savedRecently && 'text-[var(--lumi-accent-text)]',
              )}
            />
          )
        }
        label="保存快照"
        touch
        disabled={createSnapshot.isPending}
        onClick={() =>
          createSnapshot.mutate(url, {
            onSuccess: () => {
              setSavedRecently(true)
              window.setTimeout(() => setSavedRecently(false), 3000)
            },
          })
        }
      />
    </Tooltip>
  )
}

/** ReaderHeader — 标题 / 元信息 / 工具栏（0009 Gate 3 视觉重建）。
 *
 * 布局（Spec Task 12）：紧凑工具栏（IconButton 32px + Tooltip）+
 * 强标题（27px 级，Folo 实测锚点）+ 弱化元信息行。原 0006 的两个
 * 大按钮（标记已读/收藏）改为工具栏图标按钮——set 语义、共用
 * mutation 实例、pending 双禁用、key=entryRef 防泄漏等行为全部保留
 * （在 Reader.tsx 上挂 key）。
 *
 * 行为不变式（Spec 硬边界 3/5）：
 * - set 语义（PATCH 目标状态，非 toggle）；
 * - 打开原文只放行绝对 http/https（safeExternalHttpUrl），
 *   target=_blank + rel=noopener noreferrer。 */
/** Gate：语言视图三态控件（原文/双语/仅译文）。
 * 桌面 = 三段分段按钮；窄屏 = 紧凑 Menu（不遮挡/不挤出工具栏）。
 * 两态 Switch 表达不了三态，这里用显式的选项组。
 * P0-11：engine=browser 且浏览器不支持本地 Translator API 时整组
 * 禁用并给原因（不再让用户点开才发现不可用）；支持矩阵在设置页。 */
function LanguageViewControl({
  value,
  onChange,
  disabledReason,
}: {
  value: ReaderViewMode
  onChange: (mode: ReaderViewMode) => void
  /** 非 null = 当前引擎在此浏览器不可用（附原因），控件禁用。 */
  disabledReason?: string | null
}) {
  const options: { key: ReaderViewMode; label: string; short: string }[] = [
    { key: 'original', label: '原文', short: '原文' },
    { key: 'bilingual', label: '双语', short: '双语' },
    { key: 'translated', label: '仅译文', short: '译文' },
  ]
  const base =
    'inline-flex min-h-8 items-center gap-1 rounded-[var(--lumi-radius-md)] px-2 text-sm transition-colors duration-[var(--lumi-motion-fast)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]'
  const gated = disabledReason != null
  return (
    <>
      {/* 桌面分段 */}
      <div
        role="group"
        aria-label="语言视图"
        title={gated ? disabledReason : undefined}
        className="hidden items-center gap-0.5 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-0.5 lg:inline-flex"
      >
        {options.map((option) => (
          <button
            key={option.key}
            type="button"
            aria-pressed={value === option.key}
            disabled={gated && option.key !== 'original'}
            title={gated && option.key !== 'original' ? disabledReason : undefined}
            onClick={() => onChange(option.key)}
            className={cx(
              base,
              'min-w-0 px-2.5',
              value === option.key
                ? 'bg-[var(--lumi-surface-selected)] text-[var(--lumi-text-primary)]'
                : 'text-[var(--lumi-text-secondary)] hover:text-[var(--lumi-text-primary)]',
              gated && option.key !== 'original' && 'opacity-50',
            )}
          >
            {option.key === 'translated' && (
              <Languages aria-hidden className="size-3.5" />
            )}
            {option.label}
          </button>
        ))}
      </div>
      {/* 移动端紧凑菜单 */}
      <div className="lg:hidden">
        <Menu
          trigger={({ triggerProps }) => (
            <Tooltip content={gated ? disabledReason : '语言视图'}>
              <IconButton
                {...triggerProps}
                icon={<Languages aria-hidden className={cx(value !== 'original' && 'text-[var(--lumi-accent-text)]')} />}
                label={
                  gated
                    ? `语言视图不可用：${disabledReason}`
                    : `语言视图：当前 ${options.find((o) => o.key === value)?.label ?? '原文'}`
                }
                touch
                disabled={gated}
              />
            </Tooltip>
          )}
          items={options.map((o) => ({
            key: o.key,
            content: value === o.key ? <strong>✓ {o.label}</strong> : o.label,
          }))}
          onSelect={(key) => onChange(key as ReaderViewMode)}
        />
      </div>
    </>
  )
}

export default function ReaderHeader({
  detail,
  viewMode = 'original',
  onViewModeChange,
  onOpenAiConversation,
}: {
  detail: EntryDetail
  /** Gate：语言视图（由 Reader 持有；工具栏与内容区共享同一状态）。 */
  viewMode?: ReaderViewMode
  onViewModeChange?: (mode: ReaderViewMode) => void
  /** 0016：打开文章限定 AI 对话（由 Reader 持有面板开关状态）。 */
  onOpenAiConversation?: () => void
}) {
  const mutation = useEntryStateMutation()
  const { isReadLater, toggleReadLater } = useToggleReadLater()
  const readLaterMarked = isReadLater(detail.entryRef)
  const showReadingTime = useAppSettings((s) => s.settings.readerShowReadingTime)
  // P0-11：本地引擎支持门控——engine=browser 且此浏览器没有 Translator
  // API（localTranslatorAvailable() 此前导出零调用）→ 控件禁用 + 原因。
  const aiSettings = useAiSettings()
  const translationDisabledReason =
    (aiSettings.data?.translationEngine ?? 'ai') === 'browser' && !localTranslatorAvailable()
      ? '此浏览器不支持本地翻译（需要 Chrome 内置 Translator API）；可在 设置 → 翻译 更换翻译引擎。'
      : null

  // url 与 contentHtml 一样来自外部 RSS，是不可信输入：
  // 只放行绝对 http/https，其余一律不渲染「打开原文」。
  const articleUrl = safeExternalHttpUrl(detail.url)
  const published = formatPublishedAt(detail.publishedAt)
  const pending = mutation.isPending

  // 0012 Gate 5：CJK 感知阅读时间（弱化展示；开关控制）。
  // 输入用 contentText（BFF 已产出的安全纯文本）优先，回退从
  // contentHtml 提取（本地 DOMParser，不进入渲染）。仅对不可信
  // HTML做只读解析，输出只有数字。文本量极小，不 memo。
  const readingTime = showReadingTime
    ? formatReadingTime(
        detail.contentText.trim() !== ''
          ? detail.contentText
          : textFromHtml(detail.contentHtml ?? ''),
      )
    : null

  return (
    <header className="border-b border-[var(--lumi-separator)] pb-5">
      {/* 元信息行（弱化）：来源 · 作者 · 时间 · 阅读时间 */}
      <p className="text-xs text-[var(--lumi-text-tertiary)]">
        {detail.feedTitle}
        {detail.author !== null && <span> · {detail.author}</span>}
        {published !== '' && <span> · {published}</span>}
        {readingTime !== null && <span> · {readingTime}</span>}
      </p>

      {/* 强标题（Folo 锚点 27px/700；移动端略小） */}
      <h1 className="mt-2 text-[1.7rem] font-bold leading-snug text-[var(--lumi-text-primary)] max-lg:text-2xl max-lg:leading-tight">
        {detail.title}
      </h1>

      {/* 工具栏：紧凑图标按钮（桌面 32px，手机 touch 44px）。
          pending 时统一转圈，双按钮禁用（同一篇同时最多一个 PATCH）。 */}
      {/* flex-wrap：移动端窄屏溢出时换行而不是把「打开原文」挤成竖排 */}
      <div className="mt-4 flex flex-wrap items-center gap-1.5">
        {pending ? (
          <IconButton
            icon={<Loader2 aria-hidden className="animate-spin" />}
            label="处理中"
            disabled
          />
        ) : (
          <Tooltip content={detail.read ? '标记为未读' : '标记为已读'}>
            <IconButton
              icon={
                <Check
                  aria-hidden
                  className={cx(
                    detail.read
                      ? 'text-[var(--lumi-accent-text)]'
                      : 'text-current',
                  )}
                />
              }
              label={detail.read ? '标记为未读' : '标记为已读'}
              aria-pressed={detail.read}
              touch
              onClick={() =>
                mutation.mutate({
                  entryRef: detail.entryRef,
                  patch: { read: !detail.read },
                })
              }
            />
          </Tooltip>
        )}

        {/* 稍后读（0011 修正补充 §21–§23）：✓ ◷ ☆ 顺序——阅读处理 →
            临时保存 → 长期收藏；本地 marker 零网络，即时切换（乐观）；
            始终可见（不依赖 hover）；active = accent icon + subtle bg，
            同一 Clock 图标不换形（§23）。 */}
        <Tooltip content={readLaterMarked ? '从稍后读移除' : '加入稍后读'}>
          <IconButton
            icon={
              <Clock
                aria-hidden
                className={cx(
                  readLaterMarked && 'fill-[var(--lumi-accent-soft)]',
                )}
              />
            }
            label={readLaterMarked ? '从稍后读移除' : '加入稍后读'}
            aria-pressed={readLaterMarked}
            touch
            className={readLaterMarked ? 'text-[var(--lumi-accent-text)]' : undefined}
            onClick={() => toggleReadLater(detail.entryRef)}
          />
        </Tooltip>

        {pending ? (
          <IconButton
            icon={<Loader2 aria-hidden className="animate-spin" />}
            label="处理中"
            disabled
          />
        ) : (
          <Tooltip content={detail.starred ? '取消收藏' : '收藏'}>
            <IconButton
              icon={
                <Star
                  aria-hidden
                  className={cx(
                    detail.starred &&
                      'fill-[var(--lumi-category-orange)] text-[var(--lumi-category-orange)]',
                  )}
                />
              }
              label={detail.starred ? '取消收藏' : '收藏'}
              aria-pressed={detail.starred}
              touch
              onClick={() =>
                mutation.mutate({
                  entryRef: detail.entryRef,
                  patch: { starred: !detail.starred },
                })
              }
            />
          </Tooltip>
        )}

        {articleUrl !== null && (
          <a
            href={articleUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex min-h-8 items-center gap-1.5 whitespace-nowrap rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2.5 text-sm text-[var(--lumi-text-secondary)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)] hover:text-[var(--lumi-text-primary)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
          >
            <ExternalLink aria-hidden className="size-3.5" />
            打开原文
          </a>
        )}

        {/* phase2 Gate 3：保存快照——只在原文是绝对 http/https 时出现
            （articleUrl 已过 safeExternalHttpUrl）。 */}
        {articleUrl !== null && <SaveSnapshotButton url={articleUrl} />}

        {/* 0016：文章限定 AI 对话入口（右侧面板；Reader 持有开关） */}
        {onOpenAiConversation !== undefined && (
          <Tooltip content="AI 对话">
            <IconButton
              icon={<MessageSquare aria-hidden />}
              label="AI 对话"
              touch
              onClick={onOpenAiConversation}
            />
          </Tooltip>
        )}

        {/* Gate：语言视图（原文/双语/仅译文）——与 稍后读/收藏/Aa 同一
            工具栏；Reader 持有状态，正文区消费。P0-11：不支持的平台
            禁用 + 原因，不再让用户点开才发现不可用。 */}
        {onViewModeChange !== undefined && (
          <LanguageViewControl
            value={viewMode ?? 'original'}
            onChange={onViewModeChange}
            disabledReason={translationDisabledReason}
          />
        )}

        {/* 0012 Gate 7：Reader 内快速阅读样式面板（Aa）；与设置中心
            同一 settings source，不遮挡正文关键操作。 */}
        <ReaderAaPanel />
      </div>

      {mutation.isError && (
        <p className="mt-2 text-sm text-[var(--lumi-danger)]" role="alert">
          状态更新失败：{mutation.error instanceof Error ? mutation.error.message : '请稍后重试。'}
        </p>
      )}
    </header>
  )
}
