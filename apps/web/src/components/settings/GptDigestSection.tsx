/** GptDigestSection — M4：GPT 日报设置（设置中心分类页）。
 *
 * 配置：启用开关 / 发布小时 / 时区（'' = 服务器本地）/ 选材窗口 /
 * 条目上限；操作：立即生成（显式动作，忽略 enabled）、订阅地址展示与
 * 轮换（token 即凭据：只在会话认证的设置里可见）；状态：lastIssueKey、
 * lastError 与最近期刊列表。生成失败原样透出服务端 error.message。 */

import { useEffect, useState } from 'react'

import { ApiError } from '../../api/client'
import {
  useGenerateGptDigestMutation,
  useGptDigestFeed,
  useGptDigestIssues,
  useGptDigestSettings,
  useRotateGptDigestFeedMutation,
  useUpdateGptDigestSettingsMutation,
} from '../../api/queries'
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
  const settings = useGptDigestSettings()
  const issues = useGptDigestIssues()
  const feed = useGptDigestFeed()
  const updateMutation = useUpdateGptDigestSettingsMutation()
  const generateMutation = useGenerateGptDigestMutation()
  const rotateMutation = useRotateGptDigestFeedMutation()

  const [hour, setHour] = useState(8)
  const [timezone, setTimezone] = useState('')
  const [windowHours, setWindowHours] = useState(24)
  const [limitCount, setLimitCount] = useState(12)

  const loaded = settings.data
  useEffect(() => {
    if (loaded) {
      setHour(loaded.hour)
      setTimezone(loaded.timezone)
      setWindowHours(loaded.windowHours)
      setLimitCount(loaded.limitCount)
    }
  }, [loaded])

  if (settings.isPending) {
    return (
      <div className="flex flex-col gap-2" aria-label="日报设置加载中">
        {Array.from({ length: 4 }, (_, i) => (
          <Skeleton key={i} className="h-11 w-full" />
        ))}
      </div>
    )
  }
  if (settings.isError || !loaded) {
    return <p className="text-sm text-[var(--lumi-text-secondary)]">日报设置加载失败。</p>
  }

  const dirty =
    loaded.hour !== hour ||
    loaded.timezone !== timezone ||
    loaded.windowHours !== windowHours ||
    loaded.limitCount !== limitCount

  const feedUrl = feed.data ? `${window.location.origin}${feed.data.atomPath}` : ''

  return (
    <div className="flex flex-col gap-1 pb-6">
      <Row label="启用每日自动生成" hint="到点自动从窗口内的订阅内容生成一期；GET 订阅地址永远不会触发生成">
        <Switch
          id="gpt-digest-enabled"
          checked={loaded.enabled}
          onCheckedChange={(checked) => updateMutation.mutate({ enabled: checked })}
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
      <Row label="选材窗口（小时，1–72）" hint="只总结窗口内发布的内容；空窗口不生成空日报">
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
      <div className="flex items-center gap-2 py-2">
        <Button
          variant="primary"
          size="sm"
          disabled={!dirty || updateMutation.isPending}
          onClick={() => updateMutation.mutate({ hour, timezone, windowHours, limitCount })}
        >
          保存设置
        </Button>
        <Button
          variant="secondary"
          size="sm"
          disabled={generateMutation.isPending}
          onClick={() => generateMutation.mutate()}
        >
          {generateMutation.isPending ? '生成中…' : '立即生成/修订今日'}
        </Button>
      </div>
      {generateMutation.isError && generateMutation.error instanceof ApiError ? (
        <p className="text-xs text-[var(--lumi-danger-text, #b3261e)]" role="alert">
          生成失败：{generateMutation.error.message}
        </p>
      ) : null}
      {generateMutation.isSuccess ? (
        <p className="text-xs text-[var(--lumi-text-secondary)]">
          已生成/修订：{generateMutation.data.issue.title}
        </p>
      ) : null}
      {loaded.lastError ? (
        <p className="text-xs text-[var(--lumi-text-secondary)]" role="status">
          上次错误：{loaded.lastError}
        </p>
      ) : null}
      {loaded.lastIssueKey ? (
        <p className="text-xs text-[var(--lumi-text-tertiary)]">
          最近发布期号：{loaded.lastIssueKey}
        </p>
      ) : null}

      <h3 className="mt-4 text-sm font-semibold text-[var(--lumi-text-primary)]">订阅</h3>
      {feed.isPending ? (
        <Skeleton className="h-9 w-full" />
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <code className="min-w-0 flex-1 truncate rounded-[var(--lumi-radius-md)] bg-[var(--lumi-surface-pressed)] px-2 py-1.5 text-xs text-[var(--lumi-text-secondary)]">
              {feedUrl || '—'}
            </code>
            <Button variant="ghost" size="sm" onClick={() => void navigator.clipboard?.writeText(feedUrl)}>
              复制
            </Button>
            <Button
              variant="ghost"
              size="sm"
              disabled={rotateMutation.isPending}
              onClick={() => rotateMutation.mutate()}
            >
              轮换 token
            </Button>
          </div>
          <p className="text-xs text-[var(--lumi-text-tertiary)]">
            订阅地址含私密 token（持有即访问）；轮换后旧地址立即失效。
          </p>
        </>
      )}

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
