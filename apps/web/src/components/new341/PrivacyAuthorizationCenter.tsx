/** NEW-341/342/343/346/347/348 隐私与授权中心（一）—— 访问记录、
 * 第三方请求清单、敏感资料标记、设备信任、授权撤销中心、数据驻留。
 *
 * 数据全部来自 BFF 真实端点；诚实口径原样展示（无法记录的边界、
 * 未配置即「不发送」、未知项提示管理员补充）。折叠 = 不挂载 = 零查询。
 */

import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  deleteAiSendBlock,
  getAccessLog,
  getDataResidency,
  getDeviceTrust,
  getThirdPartyRequests,
  grantDeviceTrust,
  listAiSendBlocks,
  listAuthorizations,
  putAiSendBlock,
  revokeAuthorization,
  revokeDeviceTrust,
  toggleThirdPartyRequest,
} from '../../api/new341'
import { Button } from '../ui/Button'
import {
  NoteText,
  StatusLine,
  SubSection,
  actionButtonClass,
  errorText,
  inputClass,
} from './parts'

export function AccessLogSection() {
  const query = useQuery({ queryKey: ['n341-access-log'], queryFn: getAccessLog })
  if (query.isPending) return <StatusLine tone="info">加载中…</StatusLine>
  if (query.isError) return <StatusLine tone="error">{errorText(query.error)}</StatusLine>
  const log = query.data
  return (
    <div className="flex flex-col gap-2" data-n341-access-log="">
      {log.items.length === 0 ? (
        <StatusLine tone="info" testId="empty">
          暂无共享入口访问记录。
        </StatusLine>
      ) : (
        <ul className="flex flex-col gap-1">
          {log.items.map((event) => (
            <li key={event.id} data-n341-access-event={event.id} className="text-sm text-[var(--lumi-text-primary)]">
              {event.accessedAt} · {event.purposeLabel} · {event.entry}
            </li>
          ))}
        </ul>
      )}
      <NoteText>记录范围：{log.recordedScope}</NoteText>
      <div className="flex flex-col gap-1">
        {log.unrecorded.map((note) => (
          <NoteText key={note}>无法记录：{note}</NoteText>
        ))}
      </div>
    </div>
  )
}

export function ThirdPartyRequestsSection() {
  const queryClient = useQueryClient()
  const query = useQuery({ queryKey: ['n342-third-party'], queryFn: getThirdPartyRequests })
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  if (query.isPending) return <StatusLine tone="info">加载中…</StatusLine>
  if (query.isError) return <StatusLine tone="error">{errorText(query.error)}</StatusLine>
  const inventory = query.data
  async function toggle(key: string, disabled: boolean) {
    setBusy(key)
    setError(null)
    try {
      await toggleThirdPartyRequest(key, disabled)
      await queryClient.invalidateQueries({ queryKey: ['n342-third-party'] })
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(null)
    }
  }
  return (
    <div className="flex flex-col gap-2" data-n342-third-party="">
      <NoteText>{inventory.note}</NoteText>
      {[...inventory.reading, ...inventory.ai].map((item) => (
        <div key={item.key} data-n342-item={item.key} className="flex flex-wrap items-start justify-between gap-2">
          <div className="min-w-0">
            <div className="text-sm text-[var(--lumi-text-primary)]">{item.purpose}</div>
            <div className="text-xs leading-relaxed text-[var(--lumi-text-tertiary)]">
              {item.host ? `外部主机：${item.host}` : '无固定外部主机'} · {item.controlledBy}
            </div>
          </div>
          {item.optoutKey ? (
            <Button
              variant="secondary"
              disabled={busy === item.key}
              onClick={() => void toggle(item.optoutKey as string, !item.disabled)}
            >
              {item.disabled ? '恢复请求' : '关闭请求'}
            </Button>
          ) : (
            <span className="text-xs text-[var(--lumi-text-tertiary)]">
              {item.disabled ? '已关闭' : item.optional ? '可在对应设置关闭' : '必需（实例基础）'}
            </span>
          )}
        </div>
      ))}
      {error && <StatusLine tone="error">{error}</StatusLine>}
    </div>
  )
}

export function SensitiveMarksSection() {
  const queryClient = useQueryClient()
  const query = useQuery({ queryKey: ['n343-marks'], queryFn: listAiSendBlocks })
  const [entryRef, setEntryRef] = useState('')
  const [reason, setReason] = useState('')
  const [error, setError] = useState<string | null>(null)
  if (query.isPending) return <StatusLine tone="info">加载中…</StatusLine>
  if (query.isError) return <StatusLine tone="error">{errorText(query.error)}</StatusLine>
  const marks = query.data
  async function mark() {
    setError(null)
    try {
      await putAiSendBlock(entryRef.trim(), reason.trim() || undefined)
      setEntryRef('')
      setReason('')
      await queryClient.invalidateQueries({ queryKey: ['n343-marks'] })
    } catch (err) {
      setError(errorText(err))
    }
  }
  async function clear(ref: string) {
    setError(null)
    try {
      await deleteAiSendBlock(ref)
      await queryClient.invalidateQueries({ queryKey: ['n343-marks'] })
    } catch (err) {
      setError(errorText(err))
    }
  }
  return (
    <div className="flex flex-col gap-2" data-n343-marks="">
      {marks.items.length === 0 ? (
        <StatusLine tone="info" testId="empty">
          还没有标记的文章。
        </StatusLine>
      ) : (
        <ul className="flex flex-col gap-1">
          {marks.items.map((mark1) => (
            <li key={mark1.entryRef} data-n343-mark={mark1.entryRef} className="flex items-center justify-between gap-2 text-sm">
              <span className="min-w-0 truncate text-[var(--lumi-text-primary)]">
                {mark1.entryRef} · {mark1.reason}
              </span>
              <Button variant="ghost" onClick={() => void clear(mark1.entryRef)}>
                解除
              </Button>
            </li>
          ))}
        </ul>
      )}
      <div className="flex flex-col gap-2">
        <label className="flex flex-col gap-1 text-sm text-[var(--lumi-text-primary)]">
          条目引用（entryRef）
          <input
            className={inputClass}
            value={entryRef}
            onChange={(event) => setEntryRef(event.target.value)}
            placeholder="rss:…"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm text-[var(--lumi-text-primary)]">
          原因（可选，自己可见）
          <input
            className={inputClass}
            value={reason}
            onChange={(event) => setReason(event.target.value)}
          />
        </label>
        <Button className={actionButtonClass} disabled={!entryRef.trim()} onClick={() => void mark()}>
          标记为「不发送至外部 AI」
        </Button>
      </div>
      <NoteText>{marks.note}</NoteText>
      {error && <StatusLine tone="error">{error}</StatusLine>}
    </div>
  )
}

export function DeviceTrustSection() {
  const queryClient = useQueryClient()
  const query = useQuery({ queryKey: ['n346-device-trust'], queryFn: getDeviceTrust })
  const [password, setPassword] = useState('')
  const [hours, setHours] = useState('12')
  const [error, setError] = useState<string | null>(null)
  if (query.isPending) return <StatusLine tone="info">加载中…</StatusLine>
  if (query.isError) return <StatusLine tone="error">{errorText(query.error)}</StatusLine>
  const status = query.data
  async function grant() {
    setError(null)
    try {
      await grantDeviceTrust(password, Number(hours) || 12)
      setPassword('')
      await queryClient.invalidateQueries({ queryKey: ['n346-device-trust'] })
    } catch (err) {
      setError(errorText(err))
    }
  }
  async function revoke() {
    setError(null)
    try {
      await revokeDeviceTrust()
      await queryClient.invalidateQueries({ queryKey: ['n346-device-trust'] })
    } catch (err) {
      setError(errorText(err))
    }
  }
  return (
    <div className="flex flex-col gap-2" data-n346-device-trust="">
      <div className="text-sm text-[var(--lumi-text-primary)]" data-n346-current-device="">
        当前设备（{status.currentDevice.deviceLabel}）：
        {status.currentDevice.trusted
          ? `信任至 ${status.currentDevice.trustedUntil}`
          : '未授予信任'}
      </div>
      <div className="flex flex-wrap items-end gap-2">
        <label className="flex flex-col gap-1 text-sm text-[var(--lumi-text-primary)]">
          登录密码
          <input
            className={inputClass}
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoComplete="current-password"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm text-[var(--lumi-text-primary)]">
          信任时长（小时，1–720）
          <input
            className={inputClass}
            type="number"
            min={1}
            max={720}
            value={hours}
            onChange={(event) => setHours(event.target.value)}
          />
        </label>
        <Button disabled={!password} onClick={() => void grant()}>
          授予 / 续期
        </Button>
        {status.currentDevice.trusted && (
          <Button variant="secondary" onClick={() => void revoke()}>
            吊销当前设备信任
          </Button>
        )}
      </div>
      <NoteText>{status.note}</NoteText>
      {error && <StatusLine tone="error">{error}</StatusLine>}
    </div>
  )
}

export function AuthorizationsSection() {
  const queryClient = useQueryClient()
  const query = useQuery({ queryKey: ['n347-authorizations'], queryFn: listAuthorizations })
  const [error, setError] = useState<string | null>(null)
  if (query.isPending) return <StatusLine tone="info">加载中…</StatusLine>
  if (query.isError) return <StatusLine tone="error">{errorText(query.error)}</StatusLine>
  const inventory = query.data
  async function revoke(kind: string, ref: string) {
    setError(null)
    try {
      await revokeAuthorization(kind, ref)
      await queryClient.invalidateQueries({ queryKey: ['n347-authorizations'] })
    } catch (err) {
      setError(errorText(err))
    }
  }
  return (
    <div className="flex flex-col gap-2" data-n347-authorizations="">
      {inventory.items.length === 0 ? (
        <StatusLine tone="info" testId="empty">
          没有任何对外凭据面。
        </StatusLine>
      ) : (
        <ul className="flex flex-col gap-2">
          {inventory.items.map((item) => (
            <li
              key={`${item.kind}:${item.ref}`}
              data-n347-auth={`${item.kind}:${item.ref}`}
              className="flex flex-wrap items-start justify-between gap-2"
            >
              <div className="min-w-0">
                <div className="text-sm text-[var(--lumi-text-primary)]">
                  {item.label}（{item.active ? '有效' : '已撤销'})
                </div>
                <div className="text-xs leading-relaxed text-[var(--lumi-text-tertiary)]">{item.detail}</div>
                <div className="text-xs leading-relaxed text-[var(--lumi-text-tertiary)]">
                  撤销影响：{item.affected}
                </div>
              </div>
              {item.active && (
                <Button variant="secondary" onClick={() => void revoke(item.kind, item.ref)}>
                  撤销
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
      <NoteText>{inventory.note}</NoteText>
      {error && <StatusLine tone="error">{error}</StatusLine>}
    </div>
  )
}

export function ResidencySection() {
  const query = useQuery({ queryKey: ['n348-residency'], queryFn: getDataResidency })
  if (query.isPending) return <StatusLine tone="info">加载中…</StatusLine>
  if (query.isError) return <StatusLine tone="error">{errorText(query.error)}</StatusLine>
  const view = query.data
  return (
    <div className="flex flex-col gap-2" data-n348-residency="">
      <ul className="flex flex-col gap-2">
        {view.sections.map((section) => (
          <li key={section.key} data-n348-section={section.key}>
            <div className="text-sm text-[var(--lumi-text-primary)]">
              {section.title}
              {!section.known && (
                <span className="text-[var(--lumi-danger)]">（未知）</span>
              )}
            </div>
            <div className="text-xs leading-relaxed text-[var(--lumi-text-secondary)]">{section.detail}</div>
            {section.adminNote && (
              <div className="text-xs leading-relaxed text-[var(--lumi-text-tertiary)]">
                管理员说明：{section.adminNote}
              </div>
            )}
          </li>
        ))}
      </ul>
      {view.unknownKeys.length > 0 && <NoteText>{view.unknownHint}</NoteText>}
    </div>
  )
}

export function PrivacyAuthorizationCenter() {
  const [open, setOpen] = useState(false)
  return (
    <section data-n341-privacy-center="">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="min-h-8 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2.5 text-sm font-medium text-[var(--lumi-text-primary)] hover:bg-[var(--lumi-surface-hover)]"
      >
        隐私与授权中心（{open ? '收起' : '展开'}）
      </button>
      {open && (
        <div className="mt-2 flex flex-col gap-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] p-3">
          <SubSection id="n341-access-log" label="个人数据访问记录">
            <AccessLogSection />
          </SubSection>
          <SubSection id="n342-third-party" label="第三方请求清单（阅读 / AI）">
            <ThirdPartyRequestsSection />
          </SubSection>
          <SubSection id="n343-sensitive-marks" label="敏感资料标记（不发送至外部 AI）">
            <SensitiveMarksSection />
          </SubSection>
          <SubSection id="n346-device-trust" label="设备信任期限">
            <DeviceTrustSection />
          </SubSection>
          <SubSection id="n347-authorizations" label="授权撤销中心（逐项）">
            <AuthorizationsSection />
          </SubSection>
          <SubSection id="n348-residency" label="数据驻留说明">
            <ResidencySection />
          </SubSection>
        </div>
      )}
    </section>
  )
}
