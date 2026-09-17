/** GptDigestSection — M4/F01：GPT 日报（多主题配置）设置页。
 *
 * 一份配置 = 一个主题日报：独立调度/窗口/上限/单源配额/来源白名单，
 * 互不覆盖也互不串用。顶部选择配置 + 新建；表单编辑（暂停 = 关闭
 * 开关）；操作：预览选材（F06，无副作用）、立即生成/修订、订阅地址
 * 展示与复制；删除仅非默认配置可点。生成失败原样透出服务端消息。 */

import { useEffect, useState } from 'react'

import { ApiError } from '../../api/client'
import {
  useConfigFeed,
  useConfigIssues,
  useConfigPreviewMutation,
  useCreateGptDigestConfigMutation,
  useDeleteGptDigestConfigMutation,
  useGenerateConfigMutation,
  useGptDigestConfigs,
  useRotateGptDigestFeedMutation,
  useUpdateGptDigestConfigMutation,
} from '../../api/queries'
import type { GptDigestConfig } from '../../api/client'
import { Button } from '../ui/Button'
import { Switch } from '../ui/Switch'
import { Skeleton } from '../ui/Skeleton'

const numberInputCls =
  'w-20 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2.5 min-h-9 text-sm text-[var(--lumi-text-primary)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]'
const textInputCls =
  'w-full max-w-72 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2.5 min-h-9 text-sm text-[var(--lumi-text-primary)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]'

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

  const [name, setName] = useState(config.name)
  const [hour, setHour] = useState(config.hour)
  const [timezone, setTimezone] = useState(config.timezone)
  const [windowHours, setWindowHours] = useState(config.windowHours)
  const [limitCount, setLimitCount] = useState(config.limitCount)
  const [perSourceCap, setPerSourceCap] = useState(config.perSourceCap)
  const [feedUrlAllow, setFeedUrlAllow] = useState(config.feedUrlAllow)

  useEffect(() => {
    setName(config.name)
    setHour(config.hour)
    setTimezone(config.timezone)
    setWindowHours(config.windowHours)
    setLimitCount(config.limitCount)
    setPerSourceCap(config.perSourceCap)
    setFeedUrlAllow(config.feedUrlAllow)
  }, [config])

  const dirty =
    config.name !== name ||
    config.hour !== hour ||
    config.timezone !== timezone ||
    config.windowHours !== windowHours ||
    config.limitCount !== limitCount ||
    config.perSourceCap !== perSourceCap ||
    config.feedUrlAllow !== feedUrlAllow

  const feedUrl = feed.data ? `${window.location.origin}${feed.data.atomPath}` : ''

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
      <div className="flex flex-wrap items-center gap-2 py-2">
        <Button
          variant="primary"
          size="sm"
          disabled={!dirty || update.isPending}
          onClick={() =>
            update.mutate({
              configId: config.id,
              patch: { name, hour, timezone, windowHours, limitCount, perSourceCap, feedUrlAllow },
            })
          }
        >
          保存设置
        </Button>
        <Button
          variant="secondary"
          size="sm"
          disabled={preview.isPending}
          onClick={() => preview.mutate(config.id)}
        >
          {preview.isPending ? '预览中…' : '预览选材'}
        </Button>
        <Button
          variant="secondary"
          size="sm"
          disabled={generate.isPending}
          onClick={() => generate.mutate(config.id)}
        >
          {generate.isPending ? '生成中…' : '立即生成/修订今日'}
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
        <div className="flex flex-col gap-1 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] p-2.5">
          <p className="text-xs text-[var(--lumi-text-secondary)]">{preview.data.note}</p>
          <ul className="flex flex-col gap-0.5">
            {preview.data.selected.map((item) => (
              <li key={item.sourceId} className="text-xs text-[var(--lumi-text-secondary)]">
                <span className="font-medium text-[var(--lumi-text-primary)]">[{item.sourceId}]</span> {item.title}{' '}
                · {item.feedTitle}
              </li>
            ))}
            {preview.data.selected.length === 0 ? (
              <li className="text-xs text-[var(--lumi-text-tertiary)]">窗口内没有入选条目。</li>
            ) : null}
          </ul>
          <p className="text-xs text-[var(--lumi-text-tertiary)]">
            排除：窗口外 {preview.data.counts.outsideWindow ?? 0} · 白名单外{' '}
            {preview.data.counts.notAllowed ?? 0} · 自有 feed {preview.data.counts.selfFeed ?? 0} · 重复{' '}
            {preview.data.counts.duplicate ?? 0} · 超单源配额 {preview.data.counts.perSourceCapped ?? 0} · 超总量{' '}
            {preview.data.counts.overLimit ?? 0}
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
      <div>
        <Button variant="ghost" size="sm" onClick={() => rotate.mutate()}>
          轮换 token
        </Button>
      </div>

      <h3 className="mt-4 text-sm font-semibold text-[var(--lumi-text-primary)]">最近期刊</h3>
      {issues.isPending ? (
        <Skeleton className="h-9 w-full" />
      ) : issues.data && issues.data.items.length > 0 ? (
        <ul className="flex flex-col gap-1">
          {issues.data.items.map((issue) => (
            <li key={issue.issueKey} className="text-sm text-[var(--lumi-text-secondary)]">
              {issue.issueKey} · {issue.title}
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-[var(--lumi-text-tertiary)]">还没有期刊；点上方「立即生成」试一次。</p>
      )}
    </div>
  )
}
