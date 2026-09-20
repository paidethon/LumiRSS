/** GptDigestSection — M4/F01：GPT 日报（多主题配置）设置页。
 *
 * 一份配置 = 一个主题日报：独立调度/窗口/上限/单源配额/来源白名单，
 * 互不覆盖也互不串用。顶部选择配置 + 新建；表单编辑（暂停 = 关闭
 * 开关）；操作：预览选材（F06，无副作用）、立即生成/修订、订阅地址
 * 展示与复制；删除仅非默认配置可点。生成失败原样透出服务端消息。 */

import { useEffect, useState } from 'react'

import { ApiError } from '../../api/client'
import type { DigestPoolEntry, GptDigestConfig, GptDigestIssue } from '../../api/client'
import {
  useAddDigestPoolEntryMutation,
  useConfigFeed,
  useConfigIssues,
  useConfigPreviewMutation,
  useCompareFactsMutation,
  useCompareGptDigestIssueMutation,
  useCreateGptDigestConfigMutation,
  useDeleteGptDigestConfigMutation,
  useDigestPool,
  useExplainGptDigestIssueMutation,
  useGenerateConfigMutation,
  useWeeklyDigestMutation,
  useGptDigestConfigs,
  useGenerateDigestForDateMutation,
  useMissingDigestDates,
  usePublishGptDigestIssueMutation,
  useRemoveDigestPoolEntryMutation,
  useReorderDigestPoolMutation,
  useReviseGptDigestIssueMutation,
  useRotateGptDigestDryRunMutation,
  useRotateGptDigestFeedMutation,
  useUpdateGptDigestConfigMutation,
} from '../../api/queries'
import { formatTimestamp } from '../../lib/date-format'
import { Button } from '../ui/Button'
import { Switch } from '../ui/Switch'
import { Skeleton } from '../ui/Skeleton'

const numberInputCls =
  'w-20 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2.5 min-h-9 text-sm text-[var(--lumi-text-primary)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]'
const textInputCls =
  'w-full max-w-72 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2.5 min-h-9 text-sm text-[var(--lumi-text-primary)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]'
const cxText =
  'w-full rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2.5 min-h-9 text-sm text-[var(--lumi-text-primary)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]'

function Row({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="flex min-h-11 flex-wrap items-center justify-between gap-2 py-1.5">
      <div className="min-w-0">
        <div className="text-sm text-[var(--lumi-text-primary)]">{label}</div>
        {hint ? <div className="text-xs text-[var(--lumi-text-tertiary)]">{hint}</div> : null}
      </div>
      {children}
    </div>
  )
}

export function GptDigestSection() {
  const configs = useGptDigestConfigs()
  const items = configs.data?.items ?? []
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const selected: GptDigestConfig | undefined =
    items.find((c) => c.id === selectedId) ?? items[0]

  useEffect(() => {
    if (selectedId === null && items.length > 0) setSelectedId(items[0].id)
  }, [items, selectedId])

  if (configs.isPending) {
    return (
      <div className="flex flex-col gap-2" aria-label="日报设置加载中">
        {Array.from({ length: 4 }, (_, i) => (
          <Skeleton key={i} className="h-11 w-full" />
        ))}
      </div>
    )
  }
  if (configs.isError || items.length === 0) {
    return <p className="text-sm text-[var(--lumi-text-secondary)]">日报配置加载失败。</p>
  }

  return (
    <div className="flex flex-col gap-1 pb-6">
      <Row label="主题日报" hint="每份配置独立调度与选材；同一天各生成一期互不覆盖">
        <div className="flex items-center gap-2">
          <select
            aria-label="选择日报配置"
            className="min-h-9 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2.5 text-sm text-[var(--lumi-text-primary)]"
            value={selected?.id ?? ''}
            onChange={(e) => setSelectedId(Number(e.target.value))}
          >
            {items.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
                {c.enabled ? '' : '（已暂停）'}
              </option>
            ))}
          </select>
          <CreateButton onCreated={(id) => setSelectedId(id)} />
        </div>
      </Row>
      {selected ? <ConfigForm config={selected} /> : null}
    </div>
  )
}

function CreateButton({ onCreated }: { onCreated: (id: number) => void }) {
  const create = useCreateGptDigestConfigMutation()
  if (create.isError) {
    return <span className="text-xs text-[var(--lumi-text-tertiary)]">创建失败</span>
  }
  return (
    <Button
      variant="secondary"
      size="sm"
      disabled={create.isPending}
      onClick={() =>
        create.mutate(
          { name: `新日报 ${new Date().toLocaleTimeString()}` },
          { onSuccess: (created) => onCreated(created.id) },
        )
      }
    >
      新建配置
    </Button>
  )
}

function ConfigForm({ config }: { config: GptDigestConfig }) {
  const update = useUpdateGptDigestConfigMutation()
  const del = useDeleteGptDigestConfigMutation()
  const generate = useGenerateConfigMutation()
  const preview = useConfigPreviewMutation()
  const issues = useConfigIssues(config.id)
  const feed = useConfigFeed(config.id)
  const rotate = useRotateGptDigestFeedMutation()
  const rotateDry = useRotateGptDigestDryRunMutation()
  const weekly = useWeeklyDigestMutation()

  const [name, setName] = useState(config.name)
  const [hour, setHour] = useState(config.hour)
  const [timezone, setTimezone] = useState(config.timezone)
  const [windowHours, setWindowHours] = useState(config.windowHours)
  const [limitCount, setLimitCount] = useState(config.limitCount)
  const [perSourceCap, setPerSourceCap] = useState(config.perSourceCap)
  const [feedUrlAllow, setFeedUrlAllow] = useState(config.feedUrlAllow)
  const [sourceKind, setSourceKind] = useState(config.sourceKind)
  // F101：回看去重窗口（0 = 关闭，1–90 天）
  const [lookbackDays, setLookbackDays] = useState(config.lookbackDays)
  // F02：多时点（逗号分隔小时；空 = 单时点 hour）
  const [slotsText, setSlotsText] = useState(config.slots.join(','))
  // F101：本次预览显式放回的材料身份集合（url:/title: 前缀键）
  const [putBackKeys, setPutBackKeys] = useState<string[]>([])
  // F103：轮换两步确认（step: idle → 影响确认 → 已轮换展示新地址）
  const [rotateStep, setRotateStep] = useState<'idle' | 'confirm' | 'done'>('idle')

  useEffect(() => {
    setName(config.name)
    setHour(config.hour)
    setTimezone(config.timezone)
    setWindowHours(config.windowHours)
    setLimitCount(config.limitCount)
    setPerSourceCap(config.perSourceCap)
    setFeedUrlAllow(config.feedUrlAllow)
    setSourceKind(config.sourceKind)
    setLookbackDays(config.lookbackDays)
    setSlotsText(config.slots.join(','))
    setPutBackKeys([])
    setRotateStep('idle')
  }, [config])

  const parsedSlots = slotsText
    .split(/[,，\s]+/)
    .map((part) => Number(part))
    .filter((n) => Number.isInteger(n) && n >= 0 && n <= 23)
    .slice(0, 4)
    .sort((a, b) => a - b)
  const nextSlots = slotsText.trim() === '' ? [] : parsedSlots
  const slotsChanged = nextSlots.join(',') !== config.slots.join(',')

  const dirty =
    config.name !== name ||
    config.hour !== hour ||
    config.timezone !== timezone ||
    config.windowHours !== windowHours ||
    config.limitCount !== limitCount ||
    config.perSourceCap !== perSourceCap ||
    config.feedUrlAllow !== feedUrlAllow ||
    config.sourceKind !== sourceKind ||
    config.lookbackDays !== lookbackDays ||
    slotsChanged

  // §13.4：token 只存哈希——atomPath 为空 = 订阅地址已隐藏（明文不可
  // 重建），新地址经「轮换 token」一次性获取；UI 诚实呈现，不显示坏链。
  const feedUrl =
    feed.data && feed.data.atomPath !== ''
      ? `${window.location.origin}${feed.data.atomPath}`
      : ''
  const feedHidden = feed.data !== undefined && feed.data.atomPath === ''

  /** F101 放回：把材料身份加入 putBack 并以该列表重跑预览（预览即所得）。 */
  const putBackAndRepreview = (identity: string) => {
    const next = putBackKeys.includes(identity) ? putBackKeys : [...putBackKeys, identity]
    setPutBackKeys(next)
    preview.mutate({ configId: config.id, putBack: next })
  }

  const runPreview = () => {
    setPutBackKeys([])
    preview.mutate({ configId: config.id })
  }

  return (
    <div className="flex flex-col gap-1">
      <Row label="名称">
        <input
          aria-label="日报名称"
          type="text"
          className={textInputCls}
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
      </Row>
      <Row label="启用" hint="关闭 = 暂停调度；已有的期刊与订阅地址保留">
        <Switch
          id={`gpt-digest-enabled-${config.id}`}
          label={`启用 ${config.name}`}
          checked={config.enabled}
          onCheckedChange={(checked) => update.mutate({ configId: config.id, patch: { enabled: checked } })}
        />
      </Row>
      <Row label="发布小时（0–23）" hint="按下方时区解释；错过时刻后重启会当日补跑一次">
        <input
          aria-label="发布小时"
          type="number"
          min={0}
          max={23}
          className={numberInputCls}
          value={hour}
          onChange={(e) => setHour(Number(e.target.value))}
        />
      </Row>
      <Row label="时区" hint="IANA 名称，如 Asia/Shanghai；留空 = 服务器本地">
        <input
          aria-label="时区"
          type="text"
          className={textInputCls}
          placeholder="Asia/Shanghai"
          value={timezone}
          onChange={(e) => setTimezone(e.target.value)}
        />
      </Row>
      <Row label="选材窗口（小时，1–72）">
        <input
          aria-label="选材窗口小时"
          type="number"
          min={1}
          max={72}
          className={numberInputCls}
          value={windowHours}
          onChange={(e) => setWindowHours(Number(e.target.value))}
        />
      </Row>
      <Row label="近期已刊用去重（F101）" hint="回看天数（0–90）：窗口内已发布期刊引用过的材料不再入选；0 = 关闭；草稿不计入">
        <input
          aria-label="回看去重天数"
          type="number"
          min={0}
          max={90}
          className={numberInputCls}
          value={lookbackDays}
          onChange={(e) => setLookbackDays(Number(e.target.value))}
        />
      </Row>
      <Row label="单期条目上限（1–40）">
        <input
          aria-label="单期条目上限"
          type="number"
          min={1}
          max={40}
          className={numberInputCls}
          value={limitCount}
          onChange={(e) => setLimitCount(Number(e.target.value))}
        />
      </Row>
      <Row label="单一来源占比上限（0–5）" hint="每个来源最多入选条数；0 = 不限制">
        <input
          aria-label="单一来源占比上限"
          type="number"
          min={0}
          max={5}
          className={numberInputCls}
          value={perSourceCap}
          onChange={(e) => setPerSourceCap(Number(e.target.value))}
        />
      </Row>
      <Row label="来源白名单" hint="feed 地址包含任一子串才入选（换行/逗号分隔）；留空 = 全部订阅">
        <textarea
          aria-label="来源白名单"
          className={`${textInputCls} min-h-16`}
          placeholder={'tech.example.com\noss.example.org/feed'}
          value={feedUrlAllow}
          onChange={(e) => setFeedUrlAllow(e.target.value)}
        />
      </Row>
      <Row label="材料来源（F04）" hint="窗口 = 订阅时间窗；稍后读/收藏 = 生成时从对应队列取材（只读，不改状态）">
        <select
          aria-label="材料来源"
          className="min-h-9 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2.5 text-sm text-[var(--lumi-text-primary)]"
          value={sourceKind}
          onChange={(e) => setSourceKind(e.target.value)}
        >
          <option value="window">订阅窗口</option>
          <option value="read_later">稍后读队列</option>
          <option value="starred">收藏</option>
        </select>
      </Row>
      <Row label="发布时点（F02 早晚刊）" hint="逗号分隔的多个小时（如 8,20）：窗口按相邻时点切分；留空 = 单时点（用发布小时），期号退化为日期">
        <input
          aria-label="发布时点列表"
          type="text"
          className={textInputCls}
          placeholder="8,20"
          value={slotsText}
          onChange={(e) => setSlotsText(e.target.value)}
        />
      </Row>
      <div className="flex flex-wrap items-center gap-2 py-2">
        <Button
          variant="primary"
          size="sm"
          disabled={!dirty || update.isPending}
          onClick={() =>
            update.mutate({
              configId: config.id,
              patch: {
                name,
                hour,
                timezone,
                windowHours,
                limitCount,
                perSourceCap,
                feedUrlAllow,
                sourceKind,
                lookbackDays,
                slots: slotsText.trim() === '' ? [] : parsedSlots,
              },
            })
          }
        >
          保存设置
        </Button>
        <Button
          variant="secondary"
          size="sm"
          disabled={preview.isPending}
          onClick={runPreview}
        >
          {preview.isPending ? '预览中…' : '预览选材'}
        </Button>
        <Button
          variant="secondary"
          size="sm"
          disabled={generate.isPending}
          onClick={() => generate.mutate({ configId: config.id, putBack: putBackKeys })}
        >
          {generate.isPending ? '生成中…' : '立即生成/修订今日'}
        </Button>
        <Button
          variant="secondary"
          size="sm"
          disabled={weekly.isPending}
          onClick={() => weekly.mutate(config.id)}
        >
          {weekly.isPending ? '周报生成中…' : '生成周报'}
        </Button>
        {config.id > 1 ? (
          <Button
            variant="ghost"
            size="sm"
            disabled={del.isPending}
            onClick={() => {
              if (window.confirm(`删除「${config.name}」及其全部期刊？`)) del.mutate(config.id)
            }}
          >
            删除配置
          </Button>
        ) : null}
      </div>
      {weekly.isError && weekly.error instanceof ApiError ? (
        <p className="text-xs text-[var(--lumi-danger-text, #b3261e)]" role="alert">
          周报失败：{weekly.error.message}
        </p>
      ) : null}
      {generate.isError && generate.error instanceof ApiError ? (
        <p className="text-xs text-[var(--lumi-danger-text, #b3261e)]" role="alert">
          生成失败：{generate.error.message}
        </p>
      ) : null}
      {preview.isError && preview.error instanceof ApiError ? (
        <p className="text-xs text-[var(--lumi-danger-text, #b3261e)]" role="alert">
          预览失败：{preview.error.message}
        </p>
      ) : null}
      {generate.isSuccess ? (
        <p className="text-xs text-[var(--lumi-text-secondary)]">
          已生成/修订：{generate.data.issue.title}
        </p>
      ) : null}
      {config.lastError ? (
        <p className="text-xs text-[var(--lumi-text-secondary)]" role="status">
          上次错误：{config.lastError}
        </p>
      ) : null}
      {config.lastIssueKey ? (
        <p className="text-xs text-[var(--lumi-text-tertiary)]">最近发布期号：{config.lastIssueKey}</p>
      ) : null}
      {preview.data ? (
        <div className="flex flex-col gap-1 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] p-2.5" data-lumi-digest-preview="">
          <p className="text-xs text-[var(--lumi-text-secondary)]">{preview.data.note}</p>
          <ul className="flex flex-col gap-0.5">
            {preview.data.selected.map((item) => (
              <li key={item.sourceId} className="text-xs text-[var(--lumi-text-secondary)]">
                <span className="font-medium text-[var(--lumi-text-primary)]">[{item.sourceId}]</span> {item.title}{' '}
                · {item.feedTitle}
                {/* F102：manual = 来自素材池的显式候选 */}
                {item.source === 'manual' ? (
                  <span
                    className="ml-1.5 rounded-[var(--lumi-radius-full)] bg-[var(--lumi-accent-soft)] px-1.5 py-0.5 text-[10px] text-[var(--lumi-accent-text)]"
                    data-lumi-pool-manual-badge=""
                  >
                    素材池
                  </span>
                ) : null}
              </li>
            ))}
            {preview.data.selected.length === 0 ? (
              <li className="text-xs text-[var(--lumi-text-tertiary)]">窗口内没有入选条目。</li>
            ) : null}
          </ul>
          {/* F101：近期已刊用明细 + 单条放回（放回仅作用于本次预览/生成） */}
          {preview.data.excludedRecent.length > 0 ? (
            <div className="flex flex-col gap-0.5" data-lumi-excluded-recent="">
              <p className="text-xs font-medium text-[var(--lumi-text-secondary)]">
                近期已刊用（{preview.data.counts.recentIssue ?? preview.data.excludedRecent.length}，回看{' '}
                {lookbackDays} 天内已发布期刊引用过）：
              </p>
              <ul className="flex flex-col gap-0.5">
                {preview.data.excludedRecent.map((item) => {
                  const identity =
                    item.url !== '' ? `url:${item.url}` : `title:${item.title.trim().toLowerCase()}`
                  const putBack = putBackKeys.includes(identity)
                  return (
                    <li key={identity} className="flex items-center gap-2 text-xs text-[var(--lumi-text-tertiary)]">
                      <span className="min-w-0 flex-1 truncate">
                        <span
                          className="mr-1 rounded-[var(--lumi-radius-full)] bg-[var(--lumi-surface-selected)] px-1.5 py-0.5 text-[10px]"
                          data-lumi-recent-badge=""
                        >
                          近期已刊用
                        </span>
                        {item.title}
                        {item.feedTitle !== '' ? ` · ${item.feedTitle}` : ''}
                      </span>
                      <Button
                        variant="ghost"
                        size="sm"
                        data-lumi-putback={identity}
                        disabled={putBack || preview.isPending}
                        onClick={() => putBackAndRepreview(identity)}
                      >
                        {putBack ? '已放回' : '放回本次'}
                      </Button>
                    </li>
                  )
                })}
              </ul>
            </div>
          ) : null}
          {/* F102：失效素材池条目（原文删除/引用非法）诚实列出 */}
          {preview.data.poolInvalid.length > 0 ? (
            <p className="text-xs text-[var(--lumi-text-tertiary)]" data-lumi-pool-invalid="">
              素材池失效条目（已跳过）：{preview.data.poolInvalid.map((item) => `${item.entryRef}（${item.reason}）`).join('、')}
            </p>
          ) : null}
          <p className="text-xs text-[var(--lumi-text-tertiary)]">
            排除：窗口外 {preview.data.counts.outsideWindow ?? 0} · 白名单外{' '}
            {preview.data.counts.notAllowed ?? 0} · 自有 feed {preview.data.counts.selfFeed ?? 0} · 重复{' '}
            {preview.data.counts.duplicate ?? 0} · 超单源配额 {preview.data.counts.perSourceCapped ?? 0} · 超总量{' '}
            {preview.data.counts.overLimit ?? 0}
            {preview.data.counts.recentIssue !== undefined
              ? ` · 近期已刊用 ${preview.data.counts.recentIssue}`
              : ''}
          </p>
          {/* R05：来源覆盖与遗漏（只陈述事实，不做推断） */}
          {preview.data.missingSources.length > 0 ? (
            <p className="text-xs text-[var(--lumi-text-tertiary)]">
              窗口内无入选材料的订阅（{preview.data.missingSources.length}）：
              {preview.data.missingSources.map((source) => source.title || source.feedUrl).join('、')}
            </p>
          ) : (
            <p className="text-xs text-[var(--lumi-text-tertiary)]">
              本配置的订阅在窗口内均有入选材料。
            </p>
          )}
        </div>
      ) : null}

      <h3 className="mt-4 text-sm font-semibold text-[var(--lumi-text-primary)]">订阅本日报</h3>
      {feed.isPending ? (
        <Skeleton className="h-9 w-full" />
      ) : feedHidden ? (
        <p className="text-xs text-[var(--lumi-text-tertiary)]" data-lumi-feed-hidden="">
          订阅地址已隐藏（token 只存哈希，无法再次查看）；点下方「轮换 token」获取一次新地址。
        </p>
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          <code className="min-w-0 flex-1 truncate rounded-[var(--lumi-radius-md)] bg-[var(--lumi-surface-pressed)] px-2 py-1.5 text-xs text-[var(--lumi-text-secondary)]">
            {feedUrl || '—'}
          </code>
          <Button variant="ghost" size="sm" onClick={() => void navigator.clipboard?.writeText(feedUrl)}>
            复制
          </Button>
        </div>
      )}
      <p className="text-xs text-[var(--lumi-text-tertiary)]">
        订阅地址含私密 token（持有即访问）；所有配置共享同一 token，轮换后旧地址立即失效。
      </p>
      {/* F103：轮换两步——先拉影响报告（零变更），确认后才执行 */}
      <div data-lumi-digest-rotate="">
        {rotateStep === 'idle' ? (
          <Button
            variant="ghost"
            size="sm"
            disabled={rotateDry.isPending}
            onClick={() => rotateDry.mutate(undefined, { onSuccess: () => setRotateStep('confirm') })}
          >
            {rotateDry.isPending ? '读取影响中…' : '轮换 token'}
          </Button>
        ) : rotateStep === 'confirm' ? (
          <div
            className="flex flex-col gap-1.5 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] p-2.5"
            data-lumi-digest-rotate-confirm=""
          >
            <p className="text-xs font-medium text-[var(--lumi-text-primary)]">确认轮换订阅 token？</p>
            {rotateDry.data ? (
              <p className="text-xs text-[var(--lumi-text-secondary)]">
                当前 token 建于{' '}
                {rotateDry.data.impact.tokenRotatedAt != null && rotateDry.data.impact.tokenRotatedAt !== ''
                  ? `${formatTimestamp(rotateDry.data.impact.tokenRotatedAt)}${
                      rotateDry.data.impact.ageDays != null ? `（${rotateDry.data.impact.ageDays} 天前）` : ''
                    }`
                  : '（时间未知）'}
                ；所有配置共享同一 token。
              </p>
            ) : null}
            <p className="text-xs text-[var(--lumi-text-tertiary)]">
              轮换后旧链接立即失效，所有订阅方需更新地址；已发布期刊不受影响。
            </p>
            <div className="flex gap-2">
              <Button
                variant="danger"
                size="sm"
                disabled={rotate.isPending}
                onClick={() =>
                  rotate.mutate(undefined, { onSuccess: () => setRotateStep('done') })
                }
              >
                {rotate.isPending ? '轮换中…' : '确认轮换'}
              </Button>
              <Button variant="ghost" size="sm" disabled={rotate.isPending} onClick={() => setRotateStep('idle')}>
                取消
              </Button>
            </div>
          </div>
        ) : (
          <div className="flex flex-col gap-1" data-lumi-digest-rotate-done="" role="status">
            <p className="text-xs text-[var(--lumi-text-secondary)]">
              已轮换。新订阅地址（旧地址已失效，请更新订阅方）：
            </p>
            <div className="flex flex-wrap items-center gap-2">
              <code className="min-w-0 flex-1 truncate rounded-[var(--lumi-radius-md)] bg-[var(--lumi-surface-pressed)] px-2 py-1.5 text-xs text-[var(--lumi-text-secondary)]">
                {rotate.data ? `${window.location.origin}${rotate.data.atomPath}` : '—'}
              </code>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => void navigator.clipboard?.writeText(rotate.data ? `${window.location.origin}${rotate.data.atomPath}` : '')}
              >
                复制
              </Button>
            </div>
          </div>
        )}
      </div>

      <MissingDatesPanel configId={config.id} />

      <MaterialPoolPanel configId={config.id} onMergePreview={runPreview} />

      <h3 className="mt-4 text-sm font-semibold text-[var(--lumi-text-primary)]">最近期刊</h3>
      {issues.isPending ? (
        <Skeleton className="h-9 w-full" />
      ) : issues.data && issues.data.items.length > 0 ? (
        <ul className="flex flex-col gap-1.5">
          {issues.data.items.map((issue, index) => (
            <IssueRow
              key={issue.issueKey}
              configId={config.id}
              issue={issue}
              hasPrevious={index < issues.data.items.length - 1}
            />
          ))}
        </ul>
      ) : (
        <p className="text-sm text-[var(--lumi-text-tertiary)]">还没有期刊；点上方「立即生成」试一次。</p>
      )}
    </div>
  )
}

/** F08：单期行 + 展开式修订编辑（标题与各条目总结；sourceIds 不可
 * 新增——保证引用真实性不受人工编辑影响）。 */
function IssueRow({
  configId,
  issue,
  hasPrevious,
}: {
  configId: number
  issue: GptDigestIssue
  hasPrevious: boolean
}) {
  const revise = useReviseGptDigestIssueMutation()
  const publish = usePublishGptDigestIssueMutation()
  const explain = useExplainGptDigestIssueMutation()
  const compare = useCompareGptDigestIssueMutation()
  const facts = useCompareFactsMutation()
  const [editing, setEditing] = useState(false)
  const [title, setTitle] = useState(issue.title)
  const [summaries, setSummaries] = useState<string[]>(
    issue.sections.map((section) => section.items.map((item) => item.summary).join('\n')),
  )

  useEffect(() => {
    setTitle(issue.title)
    setSummaries(issue.sections.map((section) => section.items.map((item) => item.summary).join('\n')))
  }, [issue])

  const dirty =
    title !== issue.title ||
    summaries.join('\u0000') !==
      issue.sections.map((s) => s.items.map((i) => i.summary).join('\n')).join('\u0000')

  function save() {
    const sections = issue.sections.map((section, sIdx) => ({
      ...section,
      items: section.items.map((item, iIdx) => ({
        ...item,
        summary: (summaries[sIdx]?.split('\n')[iIdx] ?? item.summary).trim() || item.summary,
      })),
    }))
    revise.mutate({ configId, issueKey: issue.issueKey, payload: { title, sections } })
  }

  return (
    <li className="flex flex-col gap-1 text-sm text-[var(--lumi-text-secondary)]">
      <div className="flex items-center gap-2">
        <span className="min-w-0 flex-1 truncate">
          {issue.issueKey} · {issue.title}
        </span>
        {issue.status === 'draft' ? (
          <>
            <span
              className="shrink-0 rounded-[var(--lumi-radius-full)] bg-[var(--lumi-surface-selected)] px-2 py-0.5 text-[11px] text-[var(--lumi-text-secondary)]"
              data-lumi-digest-draft-badge=""
            >
              草稿
            </span>
            <Button
              variant="secondary"
              size="sm"
              data-lumi-digest-publish=""
              disabled={publish.isPending}
              onClick={() => publish.mutate({ configId, issueKey: issue.issueKey })}
            >
              {publish.isPending && publish.variables?.issueKey === issue.issueKey
                ? '发布中…'
                : '审阅并发布'}
            </Button>
          </>
        ) : (
          <span className="shrink-0 rounded-[var(--lumi-radius-full)] bg-[var(--lumi-accent-soft)] px-2 py-0.5 text-[11px] text-[var(--lumi-accent-text)]">
            已发布
          </span>
        )}
        {issue.issueKey.endsWith('-x') ? null : (
          <Button
            variant="ghost"
            size="sm"
            disabled={explain.isPending}
            onClick={() => explain.mutate({ configId, issueKey: issue.issueKey })}
          >
            {explain.isPending && explain.variables?.issueKey === issue.issueKey
              ? '解释中…'
              : '生成解释版'}
          </Button>
        )}
        {!issue.issueKey.endsWith('-x') && !issue.issueKey.endsWith('-d') ? (
          <Button
            variant="ghost"
            size="sm"
            disabled={facts.isPending}
            onClick={() => facts.mutate({ configId, issueKey: issue.issueKey })}
          >
            {facts.isPending && facts.variables?.issueKey === issue.issueKey
              ? '对照中…'
              : '事实对照'}
          </Button>
        ) : null}
        {issue.issueKey.endsWith('-x') || issue.issueKey.endsWith('-d') ? null : hasPrevious ? (
          <Button
            variant="ghost"
            size="sm"
            disabled={compare.isPending}
            onClick={() => compare.mutate({ configId, issueKey: issue.issueKey })}
          >
            {compare.isPending && compare.variables?.issueKey === issue.issueKey
              ? '对照中…'
              : '对照上一期'}
          </Button>
        ) : null}
        <Button variant="ghost" size="sm" onClick={() => setEditing(!editing)}>
          {editing ? '收起' : '修订'}
        </Button>
      </div>
      {compare.isError && compare.error instanceof ApiError && compare.variables?.issueKey === issue.issueKey ? (
        <p className="text-xs text-[var(--lumi-danger-text, #b3261e)]" role="alert">
          对照失败：{compare.error.message}
        </p>
      ) : null}
      {facts.data && facts.variables?.issueKey === issue.issueKey ? (
        <div
          className="rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] p-2.5 text-xs"
          data-facts-compare
          dangerouslySetInnerHTML={{ __html: facts.data.bodyHtml }}
        />
      ) : null}
      {explain.isError && explain.error instanceof ApiError && explain.variables?.issueKey === issue.issueKey ? (
        <p className="text-xs text-[var(--lumi-danger-text, #b3261e)]" role="alert">
          解释版失败：{explain.error.message}
        </p>
      ) : null}
      {editing ? (
        <div className="flex flex-col gap-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] p-2.5">
          <label className="flex flex-col gap-1">
            <span className="text-xs text-[var(--lumi-text-tertiary)]">标题</span>
            <input
              aria-label={`修订标题 ${issue.issueKey}`}
              type="text"
              className={cxText}
              value={title}
              onChange={(e) => setTitle(e.target.value)}
            />
          </label>
          {issue.sections.map((section, sIdx) =>
            section.items.map((item, iIdx) => (
              <label key={`${sIdx}-${iIdx}`} className="flex flex-col gap-1">
                <span className="text-xs text-[var(--lumi-text-tertiary)]">
                  [{item.sourceIds.join('、')}] {item.summary.slice(0, 18)}…
                </span>
                <textarea
                  aria-label={`条目总结 ${sIdx}-${iIdx}`}
                  rows={2}
                  className={cxText}
                  value={summaries[sIdx]?.split('\n')[iIdx] ?? item.summary}
                  onChange={(e) => {
                    setSummaries((prev) => {
                      const next = [...prev]
                      const lines = (next[sIdx] ?? '').split('\n')
                      lines[iIdx] = e.target.value
                      next[sIdx] = lines.join('\n')
                      return next
                    })
                  }}
                />
              </label>
            )),
          )}
          <div className="flex gap-2">
            <Button variant="primary" size="sm" disabled={!dirty || revise.isPending} onClick={save}>
              {revise.isPending ? '保存中…' : '保存修订'}
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setEditing(false)}>
              取消
            </Button>
          </div>
          {revise.isError && revise.error instanceof ApiError ? (
            <p className="text-xs text-[var(--lumi-danger-text, #b3261e)]" role="alert">
              修订失败：{revise.error.message}
            </p>
          ) : null}
        </div>
      ) : null}
    </li>
  )
}

/** F032：补刊缺失日期面板（缺失列表 + 单选 + 生成）。 */
function MissingDatesPanel({ configId }: { configId: number }) {
  const missing = useMissingDigestDates(configId)
  const generate = useGenerateDigestForDateMutation(configId)
  const [selected, setSelected] = useState('')
  const [error, setError] = useState<string | null>(null)
  if (missing.isPending || missing.isError) return null
  const dates = missing.data?.missing ?? []
  if (dates.length === 0) return null
  return (
    <div
      className="mt-3 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] px-3 py-2"
      data-lumi-digest-missing=""
    >
      <p className="text-xs font-medium text-[var(--lumi-text-secondary)]">
        补刊缺失日期（最近 30 天，{dates.length} 天缺失）
      </p>
      <div className="mt-1.5 flex flex-wrap items-center gap-2 text-xs">
        <select
          aria-label="选择缺失日期"
          value={selected}
          onChange={(e) => setSelected(e.target.value)}
          className="min-h-8 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-1.5"
        >
          <option value="">选择日期…</option>
          {dates.map((date: string) => (
            <option key={date} value={date}>
              {date}
            </option>
          ))}
        </select>
        <Button
          size="sm"
          variant="secondary"
          disabled={!selected || generate.isPending}
          onClick={() => {
            setError(null)
            generate.mutate(selected, {
              onError: (err: unknown) =>
                setError(
                  err instanceof Error && /409/.test(err.message)
                    ? '该日期已有期号，不可覆盖。'
                    : '生成失败（可能无材料或 AI 未配置）。',
                ),
            })
          }}
        >
          {generate.isPending ? '生成中…' : '补刊生成'}
        </Button>
      </div>
      {error ? (
        <p role="alert" className="mt-1 text-xs text-[var(--lumi-danger)]">
          {error}
        </p>
      ) : null}
    </div>
  )
}

/** F102：素材池面板——手工候选的列表/排序/移除 + 按 ref 加入（「加入日
 * 报待编」简化入口）+ 合并预览（与生成共用同一选材函数）。 */
function MaterialPoolPanel({
  configId,
  onMergePreview,
}: {
  configId: number
  onMergePreview: () => void
}) {
  const pool = useDigestPool(configId)
  const add = useAddDigestPoolEntryMutation(configId)
  const remove = useRemoveDigestPoolEntryMutation(configId)
  const reorder = useReorderDigestPoolMutation(configId)
  const [refInput, setRefInput] = useState('')
  const [addError, setAddError] = useState<string | null>(null)

  const pending = pool.data?.items ?? []
  const used = pool.data?.used ?? []

  const submitAdd = () => {
    const ref = refInput.trim()
    if (ref === '') return
    setAddError(null)
    add.mutate(ref, {
      onSuccess: () => setRefInput(''),
      onError: (error) => {
        if (error instanceof ApiError) {
          setAddError(error.type === 'duplicate' ? '该条目已在素材池中。' : error.message)
        } else {
          setAddError('加入失败，请稍后重试。')
        }
      },
    })
  }

  /** 上移/下移：与相邻条目交换后全量提交新顺序。 */
  const move = (index: number, direction: -1 | 1) => {
    const target = index + direction
    if (target < 0 || target >= pending.length) return
    const ids = pending.map((entry: DigestPoolEntry) => entry.id)
    const swapped = [...ids]
    ;[swapped[index], swapped[target]] = [swapped[target], swapped[index]]
    reorder.mutate(swapped)
  }

  return (
    <div
      className="mt-3 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] p-2.5"
      data-lumi-digest-pool=""
    >
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-sm font-semibold text-[var(--lumi-text-primary)]">素材池（手工候选）</h3>
        <Button
          variant="ghost"
          size="sm"
          className="ml-auto"
          disabled={previewBusy(pool) || pending.length === 0}
          onClick={onMergePreview}
          data-lumi-pool-merge-preview=""
        >
          合并预览
        </Button>
      </div>
      <p className="mt-0.5 text-xs text-[var(--lumi-text-tertiary)]">
        池内条目按顺序优先并入每期选材（source=manual）；生成消耗后移入「已刊用」。条目须来自本站订阅
        （rss: 前缀）；来源禁用 AI 时服务端会拒绝。
      </p>

      <div className="mt-2 flex flex-wrap items-center gap-2">
        <input
          aria-label="按条目引用加入素材池"
          placeholder="rss:…（条目引用）"
          value={refInput}
          onChange={(e) => setRefInput(e.target.value)}
          className="min-h-8 min-w-0 flex-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 text-xs text-[var(--lumi-text-primary)]"
        />
        <Button
          variant="secondary"
          size="sm"
          data-lumi-pool-add=""
          disabled={refInput.trim() === '' || add.isPending}
          onClick={submitAdd}
        >
          {add.isPending ? '加入中…' : '加入日报待编'}
        </Button>
      </div>
      {addError ? (
        <p role="alert" className="mt-1 text-xs text-[var(--lumi-danger-text, #b3261e)]">
          {addError}
        </p>
      ) : null}

      {pool.isPending ? (
        <Skeleton className="mt-2 h-16 w-full" />
      ) : pool.isError ? (
        <p role="alert" className="mt-2 text-xs text-[var(--lumi-danger-text, #b3261e)]">
          素材池加载失败：{pool.error instanceof Error ? pool.error.message : '请稍后重试。'}
        </p>
      ) : pending.length === 0 ? (
        <p className="mt-2 text-xs text-[var(--lumi-text-tertiary)]" data-lumi-pool-empty="">
          池为空：粘贴条目引用加入，或直接使用自动选材。
        </p>
      ) : (
        <ul className="mt-2 flex flex-col gap-1" data-lumi-pool-list="">
          {pending.map((entry, index) => (
            <li
              key={entry.id}
              className="flex items-center gap-1.5 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2 py-1.5"
              data-lumi-pool-entry={entry.entryRef}
            >
              <span className="min-w-0 flex-1 truncate text-xs text-[var(--lumi-text-secondary)]" title={entry.entryRef}>
                {index + 1}. {entry.entryRef}
              </span>
              <Button
                variant="ghost"
                size="sm"
                aria-label={`上移 ${entry.entryRef}`}
                disabled={index === 0 || reorder.isPending}
                onClick={() => move(index, -1)}
              >
                ↑
              </Button>
              <Button
                variant="ghost"
                size="sm"
                aria-label={`下移 ${entry.entryRef}`}
                disabled={index === pending.length - 1 || reorder.isPending}
                onClick={() => move(index, 1)}
              >
                ↓
              </Button>
              <Button
                variant="ghost"
                size="sm"
                aria-label={`移出素材池 ${entry.entryRef}`}
                data-lumi-pool-remove={entry.entryRef}
                disabled={remove.isPending}
                onClick={() => remove.mutate(entry.id)}
              >
                移除
              </Button>
            </li>
          ))}
        </ul>
      )}

      {used.length > 0 ? (
        <div className="mt-2" data-lumi-pool-used="">
          <p className="text-xs font-medium text-[var(--lumi-text-tertiary)]">已刊用（{used.length}）：</p>
          <ul className="mt-0.5 flex flex-col gap-0.5">
            {used.map((entry) => (
              <li key={entry.id} className="truncate text-xs text-[var(--lumi-text-tertiary)]">
                {entry.entryRef} · 期号 {entry.usedIssueKey}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  )
}

function previewBusy(pool: { isFetching: boolean }): boolean {
  return pool.isFetching
}
