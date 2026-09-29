/** NEW-303/305/304 — Webhook 接入（收）侧面板：接收端点与待确认
 * 收件箱、死信处理页、管理员签名钥轮换（受控秘密通道）。小而平；
 * 秘密只在创建/轮换响应出现一次，此后任何界面都不再回显。 */

import { useCallback, useEffect, useState, type ReactElement } from 'react'
import {
  new303Api,
  new304Api,
  new305Api,
  type DeadLetterRow,
  type InboxRow,
  type WebhookKeyRow,
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

// ---- NEW-303 接收端点 + 待确认收件箱 ----------------------------------------

export function WebhookInboxPanel(): ReactElement {
  const [label, setLabel] = useState('')
  const [created, setCreated] = useState<{
    uuid: string
    secret: string
    ingestPath: string
  } | null>(null)
  const [rows, setRows] = useState<InboxRow[]>([])
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const refresh = useCallback(async () => {
    setError('')
    try {
      const box = await new303Api.inbox()
      setRows(box.items)
    } catch (err) {
      setError(errorText(err))
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  async function createEndpoint(): Promise<void> {
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const made = await new303Api.createEndpoint(label)
      setCreated({
        uuid: made.uuid,
        secret: made.secret,
        ingestPath: made.ingestPath,
      })
      setLabel('')
      await refresh()
      setNotice('接收端点已创建；秘密仅本次显示。')
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  async function decide(row: InboxRow, accept: boolean): Promise<void> {
    setBusy(true)
    setError('')
    try {
      await new303Api.decide(row.id, accept)
      await refresh()
      setNotice(accept ? '已纳入主资料库。' : '已拒绝该条目。')
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  const pending = rows.filter((row) => row.status === 'pending')

  return (
    <div data-new303-inbox-tools="" className="flex flex-col gap-3">
      <div className="flex items-end gap-2">
        <div className="flex flex-1 flex-col gap-1">
          <label
            htmlFor="new303-endpoint-label"
            className="text-sm text-[var(--lumi-text-secondary)]"
          >
            端点名称
          </label>
          <input
            id="new303-endpoint-label"
            className={inputClass}
            value={label}
            onChange={(event) => setLabel(event.target.value)}
          />
        </div>
        <button
          type="button"
          className={buttonClass}
          disabled={busy || label === ''}
          onClick={() => void createEndpoint()}
        >
          创建接收端点
        </button>
      </div>
      {created !== null && (
        <div className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-2">
          <StatusLine tone="ok">接收地址：{created.ingestPath}</StatusLine>
          <p className="text-sm leading-relaxed break-all text-[var(--lumi-text-primary)]">
            端点秘密（仅此一次）：{created.secret}
          </p>
        </div>
      )}
      <StatusLine tone="info">
        待确认 {pending.length} 条；接受 = 纳入主资料库，拒绝 = 不入库。
      </StatusLine>
      {pending.map((row) => (
        <div
          key={row.id}
          data-new303-inbox-item={row.id}
          className="flex flex-wrap items-center gap-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-2"
        >
          <span className="text-sm font-medium text-[var(--lumi-text-primary)]">
            {row.title}
          </span>
          <span className="text-sm text-[var(--lumi-text-tertiary)]">
            {row.summary}
          </span>
          <button
            type="button"
            className={buttonClass}
            disabled={busy}
            onClick={() => void decide(row, true)}
          >
            接受
          </button>
          <button
            type="button"
            className={secondaryButtonClass}
            disabled={busy}
            onClick={() => void decide(row, false)}
          >
            拒绝
          </button>
        </div>
      ))}
      <NoteText>
        条目先进入待确认区，审阅后才纳入；接收端需要 bearer 秘密与
        实例签名钥的 HMAC 签名。
      </NoteText>
      <Feedback notice={notice} error={error} />
    </div>
  )
}

// ---- NEW-305 接入死信处理页 ---------------------------------------------------

export function DeadLetterPanel(): ReactElement {
  const [letters, setLetters] = useState<DeadLetterRow[]>([])
  const [fixedText, setFixedText] = useState('')
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const refresh = useCallback(async () => {
    setError('')
    try {
      const listed = await new305Api.list()
      setLetters(listed.items)
    } catch (err) {
      setError(errorText(err))
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  async function replay(letter: DeadLetterRow, useFixedText: boolean): Promise<void> {
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const done = await new305Api.replay(
        letter.id,
        useFixedText ? fixedText : undefined,
      )
      setNotice(
        done.replayed === true
          ? `已重放：新纳入 ${String(done.stored ?? 0)} 条。`
          : `未重放：${done.note ?? done.reason ?? '仍不可解析'}`,
      )
      await refresh()
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div data-new305-dead-tools="" className="flex flex-col gap-3">
      <StatusLine tone="info">
        死信只显示脱敏摘要（键名/类型/字节数）；原始载荷留在服务端，
        修正后可重放，绝不回显。
      </StatusLine>
      <div className="flex flex-col gap-1">
        <label
          htmlFor="new305-fixed-payload"
          className="text-sm text-[var(--lumi-text-secondary)]"
        >
          修正后的事件内容（可选，留空则用服务端留存原文重放）
        </label>
        <textarea
          id="new305-fixed-payload"
          rows={2}
          className={inputClass}
          value={fixedText}
          onChange={(event) => setFixedText(event.target.value)}
          placeholder='{"eventId":"evt-1","items":[{"id":"i1","title":"标题"}]}"}'
        />
      </div>
      {letters.map((letter) => (
        <div
          key={letter.id}
          data-new305-dead-letter={letter.id}
          className="flex flex-col gap-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-2"
        >
          <StatusLine tone={letter.status === 'pending' ? 'error' : 'info'}>
            事件 {letter.eventId} · {letter.status === 'pending' ? '待处理' : '已重放'} ·{' '}
            {letter.reason}
          </StatusLine>
          <p className="text-xs leading-relaxed text-[var(--lumi-text-tertiary)]">
            {JSON.stringify(letter.payloadSummary)}
          </p>
          {letter.status === 'pending' && (
            <button
              type="button"
              className={secondaryButtonClass}
              disabled={busy}
              onClick={() => void replay(letter, true)}
            >
              用当前内容重放
            </button>
          )}
        </div>
      ))}
      <Feedback notice={notice} error={error} />
    </div>
  )
}

// ---- NEW-304 管理员签名钥轮换（受控秘密通道） -------------------------------

export function SigningKeyAdminPanel(): ReactElement {
  const [keys, setKeys] = useState<WebhookKeyRow[]>([])
  const [password, setPassword] = useState('')
  const [windowMinutes, setWindowMinutes] = useState('10')
  const [freshSecret, setFreshSecret] = useState<string | null>(null)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const refresh = useCallback(async () => {
    setError('')
    try {
      const snapshot = await new304Api.snapshot()
      setKeys(snapshot.keys)
    } catch (err) {
      setError(errorText(err))
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  async function rotate(): Promise<void> {
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const principal = await fetch('/api/v1/auth/session').then((res) => {
        if (!res.ok) throw new Error(`会话获取失败（${res.status}）`)
        return res.json() as Promise<{ userId: string }>
      })
      const minted = await fetch('/api/v1/admin/step-up', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          password,
          operation: 'webhook_key_rotation',
          targetUserId: principal.userId,
        }),
      })
      if (!minted.ok) throw new Error(`提权失败（${minted.status}）`)
      const mintBody = (await minted.json()) as { token: string }
      const rotated = await new304Api.rotate(
        mintBody.token,
        Number(windowMinutes),
      )
      setFreshSecret(rotated.secret)
      setPassword('')
      setNotice(
        `新钥 ${rotated.keyId} 已启用；旧钥 ${rotated.previousKeyId ?? '（无）'} ` +
          `在 ${String(rotated.windowMinutes)} 分钟内仍可验证。`,
      )
      await refresh()
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div data-new304-key-tools="" className="flex flex-col gap-3">
      <div className="flex items-end gap-2">
        <div className="flex flex-1 flex-col gap-1">
          <label
            htmlFor="new304-admin-password"
            className="text-sm text-[var(--lumi-text-secondary)]"
          >
            管理员密码（本会话内重新证明）
          </label>
          <input
            id="new304-admin-password"
            type="password"
            className={inputClass}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
        </div>
        <div className="flex flex-col gap-1">
          <label
            htmlFor="new304-window"
            className="text-sm text-[var(--lumi-text-secondary)]"
          >
            双钥窗口（分钟，1..60）
          </label>
          <input
            id="new304-window"
            type="number"
            min={1}
            max={60}
            className={inputClass}
            value={windowMinutes}
            onChange={(event) => setWindowMinutes(event.target.value)}
          />
        </div>
        <button
          type="button"
          className={buttonClass}
          disabled={busy || password === ''}
          onClick={() => void rotate()}
        >
          轮换签名钥
        </button>
      </div>
      {freshSecret !== null && (
        <p className="text-sm leading-relaxed break-all rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-2 text-[var(--lumi-text-primary)]">
          新钥明文（仅此一次，请立即交付发送方）：{freshSecret}
        </p>
      )}
      <StatusLine tone="info">切换结果（每钥每日成功验证计数）：</StatusLine>
      {keys.map((key) => (
        <p
          key={key.keyId}
          data-new304-key-row={key.keyId}
          className="text-sm leading-relaxed text-[var(--lumi-text-secondary)]"
        >
          {key.keyId} · {key.state} · 今日验证 {key.verifiedToday} / 累计{' '}
          {key.verifiedTotal}
        </p>
      ))}
      <NoteText>报告不含任何密钥材料；新钥计数上升且旧钥归零即切换完成。</NoteText>
      <Feedback notice={notice} error={error} />
    </div>
  )
}
