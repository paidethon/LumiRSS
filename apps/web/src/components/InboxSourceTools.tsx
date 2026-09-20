/** InboxSourceTools — W6 收件连接器工具（F107/F108/F109）。
 *
 * - F107 投递记录：每连接器的事件流（delivered/duplicate/failed），
 *   failed 行可重放（复用原载荷 + (source, guid) 幂等）；
 * - F108 接入检查：与正式 ingest 同一校验函数的零写入试跑面板
 *   （JSON 编辑 → valid/errors/wouldCreate/notes/wouldDuplicate）；
 * - F109 轮换凭据：武装确认 → rotate → 一次性 secret 展示（旧令牌
 *   自下一请求起立即失效；已推送条目不受影响）。
 */

import { useState } from 'react'
import { History, RotateCw, ShieldCheck } from 'lucide-react'

import { ApiError } from '../api/client'
import type { IngestDryRunResult } from '../api/client'
import type { InboxSourceCreated } from '../api/types'
import type { InboxEvent } from '../api/client'
import {
  useInboxEvents,
  useIngestDryRunMutation,
  useReplayInboxEventMutation,
  useRotateInboxSourceMutation,
} from '../api/queries'
import { formatTimestamp } from '../lib/date-format'
import { Button } from './ui/Button'
import { CopyField } from './pages/InboxPage'
import { Dialog } from './ui/Dialog'
import { Skeleton } from './ui/Skeleton'
import { cx } from './ui/cx'

function errorText(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return error.message
  if (error instanceof Error) return error.message
  return fallback
}

// ---- F107：投递记录 ----------------------------------------------------------

function DeliveryEventsPanel({ sourceUuid, name, onClose }: { sourceUuid: string; name: string; onClose: () => void }) {
  const events = useInboxEvents(sourceUuid)
  const replay = useReplayInboxEventMutation(sourceUuid)

  const items = events.data?.items ?? []

  return (
    <Dialog
      open
      onClose={onClose}
      title={`投递记录：${name}`}
      footer={
        <Button variant="primary" size="sm" onClick={onClose}>
          完成
        </Button>
      }
    >
      <div className="flex flex-col gap-2 text-sm" data-inbox-events-panel="">
        <p className="text-xs text-[var(--lumi-text-secondary)]">
          每次投递落一条事件（最近 50 条）；失败事件可用原始载荷重放——重复投递被幂等吸收，不会产生新条目。
        </p>
        {events.isPending && <Skeleton className="h-16 w-full" />}
        {events.isError && (
          <p role="alert" className="text-xs text-[var(--lumi-danger)]">
            {errorText(events.error, '事件加载失败。')}
          </p>
        )}
        {events.isSuccess && items.length === 0 && (
          <p className="text-xs text-[var(--lumi-text-tertiary)]" data-events-empty="">
            还没有投递事件。
          </p>
        )}
        <ul className="flex flex-col gap-1.5">
          {items.map((event: InboxEvent) => (
            <li
              key={event.id}
              className="flex items-center gap-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2 py-1.5"
              data-inbox-event={event.id}
            >
              <span
                className={cx(
                  'shrink-0 rounded-[var(--lumi-radius-full)] px-1.5 py-0.5 text-[10px]',
                  event.status === 'failed'
                    ? 'bg-[var(--lumi-danger)]/10 text-[var(--lumi-danger)]'
                    : 'bg-[var(--lumi-accent-soft)] text-[var(--lumi-accent-text)]',
                )}
              >
                {event.status === 'delivered' ? '已投递' : event.status === 'duplicate' ? '重复' : '失败'}
              </span>
              <span className="min-w-0 flex-1 truncate text-xs text-[var(--lumi-text-secondary)]">
                {event.guid}
                {event.errorSummary ? ` · ${event.errorSummary}` : ''}
                <span className="ml-1 text-[var(--lumi-text-tertiary)]">{formatTimestamp(event.createdAt)}</span>
              </span>
              {event.status === 'failed' && (
                <Button
                  variant="secondary"
                  size="sm"
                  data-event-replay={event.id}
                  aria-label={`重放 ${event.id}`}
                  disabled={replay.isPending}
                  onClick={() => replay.mutate(event.id)}
                >
                  {replay.isPending && replay.variables === event.id ? '重放中…' : '重放'}
                </Button>
              )}
            </li>
          ))}
        </ul>
        {replay.isSuccess && (
          <p role="status" className="text-xs text-[var(--lumi-text-secondary)]" data-replay-ok="">
            重放完成：{replay.data.status === 'created' ? '已创建新条目' : `状态 ${replay.data.status}`}。
          </p>
        )}
        {replay.isError && (
          <p role="alert" className="text-xs text-[var(--lumi-danger)]" data-replay-fail="">
            重放失败：{errorText(replay.error, '请稍后重试。')}
          </p>
        )}
      </div>
    </Dialog>
  )
}

// ---- F108：接入检查（零写入试跑） ---------------------------------------------

const SAMPLE_PAYLOAD = '{\n  "guid": "demo-1",\n  "title": "示例标题",\n  "content_text": "正文"\n}'

function IngestDryRunPanel({ sourceUuid, name, onClose }: { sourceUuid: string; name: string; onClose: () => void }) {
  const dryRun = useIngestDryRunMutation(sourceUuid)
  const [payload, setPayload] = useState(SAMPLE_PAYLOAD)

  const result: IngestDryRunResult | undefined = dryRun.data
  return (
    <Dialog
      open
      onClose={onClose}
      title={`接入检查：${name}`}
      footer={
        <Button variant="primary" size="sm" onClick={onClose}>
          完成
        </Button>
      }
    >
      <div className="flex flex-col gap-2 text-sm" data-inbox-dryrun-panel="">
        <p className="text-xs text-[var(--lumi-text-secondary)]">
          与正式推送同一校验函数的<strong>零写入</strong>试跑：不落库、不产生条目。未知字段与嵌套超限只提示不拦截。
        </p>
        <textarea
          aria-label="接入载荷 JSON"
          value={payload}
          onChange={(event) => setPayload(event.target.value)}
          rows={8}
          className="w-full rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-2 font-mono text-xs text-[var(--lumi-text-primary)]"
        />
        <div>
          <Button
            variant="secondary"
            size="sm"
            data-dryrun-go=""
            disabled={dryRun.isPending || payload.trim() === ''}
            onClick={() => dryRun.mutate(payload)}
          >
            {dryRun.isPending ? '检查中…' : '零写入试跑'}
          </Button>
        </div>
        {result && (
          <div className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-2.5" data-dryrun-output="">
            {result.valid ? (
              <p role="status" className="text-xs text-[var(--lumi-success)]" data-dryrun-valid="">
                校验通过：将创建「{result.wouldCreate?.title ?? '（无标题）'}」
                {result.wouldDuplicate ? '（该 guid 已存在，重复投递会被幂等吸收）' : ''}
              </p>
            ) : (
              <ul className="flex flex-col gap-0.5" role="alert" data-dryrun-invalid="">
                {result.errors.map((item) => (
                  <li key={`${item.field}-${item.reason}`} className="text-xs text-[var(--lumi-danger)]">
                    {item.field}：{item.reason}
                  </li>
                ))}
              </ul>
            )}
            <div data-dryrun-notes="">
              {result.notes.map((note) => (
                <p key={note} className="text-xs text-[var(--lumi-text-tertiary)]">
                  {note}
                </p>
              ))}
            </div>
          </div>
        )}
        {dryRun.isError && (
          <p role="alert" className="text-xs text-[var(--lumi-danger)]">
            {errorText(dryRun.error, '试跑失败。')}
          </p>
        )}
      </div>
    </Dialog>
  )
}

// ---- F109：轮换凭据 ----------------------------------------------------------

export function InboxSourceTools({ sourceUuid, name }: { sourceUuid: string; name: string }) {
  const [panel, setPanel] = useState<'events' | 'dryrun' | null>(null)
  const [rotateArmed, setRotateArmed] = useState(false)
  const [rotated, setRotated] = useState<InboxSourceCreated | null>(null)
  const rotate = useRotateInboxSourceMutation()

  return (
    <>
      <Button
        variant="ghost"
        size="sm"
        data-inbox-events-open={sourceUuid}
        onClick={() => setPanel('events')}
        aria-label={`投递记录 ${name}`}
      >
        <History aria-hidden className="size-3.5" />
      </Button>
      <Button
        variant="ghost"
        size="sm"
        data-inbox-dryrun-open={sourceUuid}
        onClick={() => setPanel('dryrun')}
        aria-label={`接入检查 ${name}`}
      >
        <ShieldCheck aria-hidden className="size-3.5" />
      </Button>
      {rotateArmed ? (
        <>
          <Button
            variant="danger"
            size="sm"
            data-rotate-arm={sourceUuid}
            disabled={rotate.isPending}
            onClick={() =>
              rotate.mutate(sourceUuid, {
                onSuccess: (created) => {
                  setRotated(created)
                  setRotateArmed(false)
                },
              })
            }
          >
            {rotate.isPending ? '轮换中…' : '确认轮换'}
          </Button>
          <Button variant="ghost" size="sm" disabled={rotate.isPending} onClick={() => setRotateArmed(false)}>
            取消
          </Button>
        </>
      ) : (
        <Button
          variant="ghost"
          size="sm"
          data-inbox-rotate-open={sourceUuid}
          aria-label={`轮换凭据 ${name}`}
          disabled={rotate.isPending}
          onClick={() => setRotateArmed(true)}
        >
          <RotateCw aria-hidden className="size-3.5" />
        </Button>
      )}
      {rotate.isError && (
        <span role="alert" className="text-xs text-[var(--lumi-danger)]">
          {errorText(rotate.error, '轮换失败。')}
        </span>
      )}

      {panel === 'events' && (
        <DeliveryEventsPanel sourceUuid={sourceUuid} name={name} onClose={() => setPanel(null)} />
      )}
      {panel === 'dryrun' && (
        <IngestDryRunPanel sourceUuid={sourceUuid} name={name} onClose={() => setPanel(null)} />
      )}
      {rotated !== null && (
        <Dialog
          open
          onClose={() => setRotated(null)}
          title="凭据已轮换"
          footer={
            <Button variant="primary" size="sm" onClick={() => setRotated(null)}>
              完成
            </Button>
          }
        >
          <div className="flex flex-col gap-3 text-sm" data-rotate-once="">
            <p className="text-[var(--lumi-text-secondary)]">
              新凭据<strong className="text-[var(--lumi-text-primary)]">仅显示这一次</strong>；旧令牌自下一请求起立即失效。
            </p>
            <CopyField label="摄取地址（POST，完整 URL）" value={`${window.location.origin}${rotated.ingestPath}`} onCopy={() => {}} mono />
            <CopyField label="新 Bearer Secret" value={rotated.secret} onCopy={() => {}} mono />
            <p className="text-xs text-[var(--lumi-text-tertiary)]">
              已推送的条目不受影响；请立即更新你的推送脚本。
            </p>
          </div>
        </Dialog>
      )}
    </>
  )
}
