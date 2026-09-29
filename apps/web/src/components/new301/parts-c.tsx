/** NEW-308/309/310 — Webhook 外发（出）侧与配置转移面板：事件订阅
 * （验证门/暂停/撤销/测试发送）、投递回执（脱敏/同一幂等键重试）、
 * 接入配置转移包（无秘密导出/凭据引用重选导入）。小而平。 */

import { useCallback, useEffect, useState, type ReactElement } from 'react'
import {
  new308Api,
  new309Api,
  new310Api,
  type DeliveryRow,
  type OutSubscriptionRow,
  type TransferSourceEntry,
} from '../../api/new301'
import {
  buttonClass,
  errorText,
  inputClass,
  secondaryButtonClass,
  NoteText,
  StatusLine,
} from '../new271/panel'

function Feedback(props: { notice: string; error: string }): ReactElement {
  return (
    <>
      {props.notice !== '' && <StatusLine tone="ok">{props.notice}</StatusLine>}
      {props.error !== '' && <StatusLine tone="error">{props.error}</StatusLine>}
    </>
  )
}

function itemsOf<T>(response: { items?: T[] } | null): T[] {
  if (response === null || response.items === undefined) return []
  return Array.isArray(response.items) ? response.items : []
}

// ---- NEW-308 外发 Webhook 事件订阅 -------------------------------------------

const EVENT_LABELS: Record<string, string> = {
  'entry.starred': '条目被标星',
  'library.item_created': '收录了新条目',
  'reading.progress_changed': '阅读进度变化',
}

export function OutSubscriptionPanel(): ReactElement {
  const [subs, setSubs] = useState<OutSubscriptionRow[]>([])
  const [eventTypes, setEventTypes] = useState<string[]>([])
  const [eventType, setEventType] = useState('entry.starred')
  const [targetUrl, setTargetUrl] = useState('')
  const [verifyToken, setVerifyToken] = useState('')
  const [pendingId, setPendingId] = useState<number | null>(null)
  const [createdOnce, setCreatedOnce] = useState<{
    secret: string
    verifyToken: string
  } | null>(null)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const refresh = useCallback(async () => {
    setError('')
    try {
      const listed = await new308Api.list()
      setSubs(listed.items)
      setEventTypes(listed.eventTypes)
    } catch (err) {
      setError(errorText(err))
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  async function createSub(): Promise<void> {
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const made = await new308Api.create(sub_eventValue(), targetUrl)
      setCreatedOnce({ secret: made.secret, verifyToken: verifyToken })
      setPendingId(made.id)
      setTargetUrl('')
      await refresh()
      setNotice('订阅已创建（待验证）；秘密与验证令牌仅本次显示。')
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  function sub_eventValue(): string {
    return EVENT_LABELS[eventType] !== undefined ? eventType : 'entry.starred'
  }

  async function actRow(
    row: OutSubscriptionRow,
    action: 'verify' | 'pause' | 'resume' | 'revoke' | 'test',
    tokenText?: string,
  ): Promise<void> {
    setBusy(true)
    setError('')
    setNotice('')
    try {
      if (action === 'verify') {
        await new308Api.verify(row.id, tokenText ?? '')
        setNotice('目标地址已验证；订阅生效。')
      } else if (action === 'pause') {
        await new308Api.pause(row.id)
        setNotice('已暂停发送。')
      } else if (action === 'resume') {
        await new308Api.resume(row.id)
        setNotice('已恢复发送。')
      } else if (action === 'revoke') {
        await new308Api.revoke(row.id)
        setNotice('已撤销（终态；历史回执保留）。')
      } else {
        const results = await new308Api.dispatch(
          row.eventType,
          { sample: true, note: 'Lumi 测试事件' },
        )
        setNotice(`测试事件已处理 ${String(results.results.length)} 个订阅。`)
      }
      await refresh()
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div data-new308-out-tools="" className="flex flex-col gap-3">
      <div className="flex items-end gap-2">
        <div className="flex flex-col gap-1">
          <label
            htmlFor="new308-event-type"
            className="text-sm text-[var(--lumi-text-secondary)]"
          >
            事件类型
          </label>
          <select
            id="new308-event-type"
            className={inputClass}
            value={eventType}
            onChange={(event) => setEventType(event.target.value)}
          >
            {eventTypes.map((one) => (
              <option key={one} value={one}>
                {EVENT_LABELS[one] ?? one}
              </option>
            ))}
          </select>
        </div>
        <div className="flex flex-1 flex-col gap-1">
          <label
            htmlFor="new308-target-url"
            className="text-sm text-[var(--lumi-text-secondary)]"
          >
            目标地址（仅 https）
          </label>
          <input
            id="new308-target-url"
            className={inputClass}
            value={targetUrl}
            onChange={(event) => setTargetUrl(event.target.value)}
            placeholder="https://your-service.example/hook"
          />
        </div>
        <button
          type="button"
          className={buttonClass}
          disabled={busy || targetUrl === ''}
          onClick={() => void createSub()}
        >
          创建订阅
        </button>
      </div>
      {createdOnce !== null && (
        <p className="text-sm leading-relaxed break-all rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-2 text-[var(--lumi-text-primary)]">
          签名秘密（仅此一次）：{createdOnce.secret} · 验证令牌：
          {createdOnce.verifyToken}
        </p>
      )}
      {subs.map((sub) => (
        <div
          key={sub.id}
          data-new308-sub={sub.id}
          className="flex flex-col gap-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-2"
        >
          <StatusLine
            tone={sub.state === 'revoked' ? 'info' : sub.state === 'active' ? 'ok' : 'error'}
          >
            {EVENT_LABELS[sub.eventType] ?? sub.eventType} → {sub.targetHost} ·{' '}
            {sub.state === 'active'
              ? '生效中'
              : sub.state === 'pending'
                ? '待验证'
                : sub.state === 'paused'
                  ? '已暂停'
                  : '已撤销'}
          </StatusLine>
          <div className="flex flex-wrap items-center gap-2">
            {sub.state === 'pending' && (
              <button
                type="button"
                className={secondaryButtonClass}
                disabled={busy}
                onClick={() => void actRow(sub, 'verify', verifyToken)}
              >
                用令牌验证
              </button>
            )}
            {sub.state === 'active' && (
              <>
                <button
                  type="button"
                  className={secondaryButtonClass}
                  disabled={busy}
                  onClick={() => void actRow(sub, 'pause')}
                >
                  暂停
                </button>
                <button
                  type="button"
                  className={secondaryButtonClass}
                  disabled={busy}
                  onClick={() => void actRow(sub, 'test')}
                >
                  发测试事件
                </button>
              </>
            )}
            {sub.state === 'paused' && (
              <button
                type="button"
                className={secondaryButtonClass}
                disabled={busy}
                onClick={() => void actRow(sub, 'resume')}
              >
                恢复
              </button>
            )}
            {sub.state !== 'revoked' && (
              <button
                type="button"
                className={secondaryButtonClass}
                disabled={busy}
                onClick={() => void actRow(sub, 'revoke')}
              >
                撤销
              </button>
            )}
          </div>
        </div>
      ))}
      <div className="flex flex-col gap-1 border-t border-[var(--lumi-border)] pt-2">
        <label
          htmlFor="new308-verify-token"
          className="text-sm text-[var(--lumi-text-secondary)]"
        >
          待验证订阅的验证令牌
        </label>
        <input
          id="new308-verify-token"
          className={inputClass}
          value={verifyToken}
          onChange={(event) => setVerifyToken(event.target.value)}
        />
      </div>
      <Feedback notice={notice} error={error} />
    </div>
  )
}

// ---- NEW-309 投递回执 -------------------------------------------------------

export function DeliveryReceiptPanel(): ReactElement {
  const [rows, setRows] = useState<DeliveryRow[]>([])
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const refresh = useCallback(async () => {
    setError('')
    try {
      const listed = await new309Api.list()
      setRows(listed.items)
    } catch (err) {
      setError(errorText(err))
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  async function retry(row: DeliveryRow): Promise<void> {
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const receipt = await new309Api.retry(row.id)
      setNotice(
        `重试完成（第 ${String(receipt.attempt)} 次尝试，同一幂等键 ${`${
          receipt.idempotencyKey.slice(0, 8)
        }…`}）：${receipt.status}`,
      )
      await refresh()
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  async function processDue(): Promise<void> {
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const outcome = await new309Api.processDue()
      setNotice(`已处理到点重试 ${String(outcome.processed)} / 到点 ${String(outcome.due)}。`)
      await refresh()
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div data-new309-receipt-tools="" className="flex flex-col gap-3">
      <button
        type="button"
        className={secondaryButtonClass}
        disabled={busy}
        onClick={() => void processDue()}
      >
        处理到点的计划重试
      </button>
      {rows.length === 0 && (
        <StatusLine tone="info">还没有投递记录。</StatusLine>
      )}
      {rows.map((row) => (
        <div
          key={row.id}
          data-new309-delivery={row.id}
          className="flex flex-col gap-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-2"
        >
          <StatusLine
            tone={row.status === 'success' ? 'ok' : row.status === 'failed' ? 'error' : 'info'}
          >
            #{String(row.attempt)} {row.eventType} · {statusLabel(row.status)} ·
            HTTP {row.responseStatus === null ? '—' : String(row.responseStatus)} ·
            幂等键 {row.idempotencyKey.slice(0, 8)}…
            {row.nextRetryAt !== null ? ` · 下次重试 ${row.nextRetryAt}` : ''}
          </StatusLine>
          {row.responseExcerpt !== null && (
            <p className="text-xs leading-relaxed text-[var(--lumi-text-tertiary)]">
              {row.responseExcerpt}
            </p>
          )}
          {row.status !== 'success' && (
            <button
              type="button"
              className={secondaryButtonClass}
              disabled={busy}
              onClick={() => void retry(row)}
            >
              手动重试（同一幂等标识）
            </button>
          )}
        </div>
      ))}
      <NoteText>回执只含脱敏响应摘要；签名与请求头永不回显。</NoteText>
      <Feedback notice={notice} error={error} />
    </div>
  )
}

function statusLabel(status: string): string {
  if (status === 'success') return '成功'
  if (status === 'failed') return '失败（计划内将重试）'
  return '已达尝试上限'
}

// ---- NEW-310 接入配置转移包 ---------------------------------------------------

export function TransferBundlePanel(): ReactElement {
  const [sources, setSources] = useState<TransferSourceEntry[]>([])
  const [honesty, setHonesty] = useState('')
  const [choices, setChoices] = useState<Record<string, string>>({})
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const refresh = useCallback(async () => {
    setError('')
    try {
      const exported = await new310Api.export()
      setSources(exported.sources)
      setHonesty(exported.honestyNote)
      const nextChoices: Record<string, string> = {}
      for (const entry of exported.sources) {
        nextChoices[entry.credentialRef] = 'generate'
      }
      setChoices(nextChoices)
    } catch (err) {
      setError(errorText(err))
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  async function importNow(): Promise<void> {
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const outcome = await new310Api.importBundle(
        { sources: sources },
        choices,
      )
      setNotice(
        `导入完成：新建 ${String(outcome.created.length)} · 合并 ${String(
          outcome.merged.length,
        )} · 跳过 ${String(outcome.skipped.length)}`,
      )
      for (const item of outcome.created) {
        void item.credentialNote
      }
      await refresh()
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }


  return (
    <div data-new310-transfer-tools="" className="flex flex-col gap-3">
      <StatusLine tone="info">
        {honesty === '' ? '导出中…' : honesty}
      </StatusLine>
      {sources.map((entry) => (
        <div
          key={entry.credentialRef}
          data-new310-entry={entry.credentialRef}
          className="flex flex-wrap items-end gap-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-2"
        >
          <span className="text-sm text-[var(--lumi-text-primary)]">{entry.name}</span>
          <div className="flex flex-col gap-1">
            <label
              htmlFor={`new310-cred-${entry.credentialRef.slice(-8)}`}
              className="text-sm text-[var(--lumi-text-secondary)]"
            >
              凭据引用
            </label>
            <select
              id={`new310-cred-${entry.credentialRef.slice(-8)}`}
              className={inputClass}
              value={choices[entry.credentialRef] ?? 'generate'}
              onChange={(event) =>
                setChoices({ ...choices, [entry.credentialRef]: event.target.value })
              }
            >
              <option value="generate">新建并铸造新凭据</option>
            </select>
          </div>
        </div>
      ))}
      <button
        type="button"
        className={buttonClass}
        disabled={busy || sources.length === 0}
        onClick={() => void importNow()}
      >
        导入为 本实例配置
      </button>
      <NoteText>包内不含任何秘密与运行状态；导入响应也不回显凭据。</NoteText>
      <Feedback notice={notice} error={error} />
    </div>
  )
}
