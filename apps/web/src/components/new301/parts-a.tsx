/** 来源级接入面板：字段映射样本、分页试抓台、抓取变更预警、来源配额。
 * 挂载点 = 来源详情抽屉（字段 / 抓取 tab）。小而平：载入 → 动作 →
 * 状态行；仅 --lumi-* 语义令牌；输入均有 label（可访问性）。
 * new301 等小写标识仅是内部文件命名，用户可见文案使用自然语言。 */

import { useCallback, useEffect, useRef, useState, type ReactElement } from 'react'
import {
  new301Api,
  new302Api,
  new306Api,
  new307Api,
  type IntakeQuotaSnapshot,
  type MappingSample,
  type ProbeResult,
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

function isAbort(err: unknown): boolean {
  return err instanceof DOMException && err.name === 'AbortError'
}

// ---- 字段映射编辑器（样本保存 / 试映射 / 绑定） -----------------------------

export function MappingSamplePanel(props: {
  sourceUuid: string | undefined
}): ReactElement {
  const [samples, setSamples] = useState<MappingSample[]>([])
  const [label, setLabel] = useState('')
  const [sampleText, setSampleText] = useState('')
  const [idExpr, setIdExpr] = useState('id')
  const [titleExpr, setTitleExpr] = useState('name')
  const [preview, setPreview] = useState<{ total: number; rows: Record<string, unknown>[] } | null>(null)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const refresh = useCallback(async () => {
    if (props.sourceUuid === undefined) {
      setSamples([])
      return
    }
    setError('')
    try {
      const found = await new301Api.listSamples(props.sourceUuid)
      setSamples(found.items)
    } catch (err) {
      setError(errorText(err))
    }
  }, [props.sourceUuid])

  useEffect(() => {
    void refresh()
  }, [refresh])

  async function saveSample(): Promise<void> {
    if (props.sourceUuid === undefined) return
    let parsed: unknown
    try {
      parsed = JSON.parse(sampleText)
    } catch {
      setError('不是合法 JSON，请检查后重试。')
      return
    }
    setBusy(true)
    setError('')
    setNotice('')
    try {
      await new301Api.save(props.sourceUuid, label, parsed)
      await refresh()
      setNotice('样本已保存。')
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  async function previewWith(sampleId: number): Promise<void> {
    if (props.sourceUuid === undefined) return
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const result = await new301Api.preview(
        props.sourceUuid,
        sampleId,
        { id: idExpr, title: titleExpr },
      )
      setPreview({ total: result.totalAvailable, rows: result.items })
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  async function bindMapping(): Promise<void> {
    if (props.sourceUuid === undefined) return
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const bound = await new301Api.bind(props.sourceUuid, {
        id: idExpr,
        title: titleExpr,
      })
      setNotice(bound.note)
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div data-intake-mapping-tools="" className="flex flex-col gap-3">
      <div className="flex flex-col gap-1">
        <label htmlFor="intake-sample-label" className="text-sm text-[var(--lumi-text-secondary)]">
          样本名称
        </label>
        <input
          id="intake-sample-label"
          className={inputClass}
          value={label}
          onChange={(event) => setLabel(event.target.value)}
        />
      </div>
      <div className="flex flex-col gap-1">
        <label htmlFor="intake-sample-json" className="text-sm text-[var(--lumi-text-secondary)]">
          JSON 样本
        </label>
        <textarea
          id="intake-sample-json"
          rows={3}
          className={inputClass}
          value={sampleText}
          onChange={(event) => setSampleText(event.target.value)}
          placeholder='{"items":[{"id":1,"name":"标题"}]}'
        />
      </div>
      <div className="flex items-end gap-2">
        <div className="flex flex-col gap-1">
          <label htmlFor="intake-field-id" className="text-sm text-[var(--lumi-text-secondary)]">
            标识表达式
          </label>
          <input
            id="intake-field-id"
            className={inputClass}
            value={idExpr}
            onChange={(event) => setIdExpr(event.target.value)}
          />
        </div>
        <div className="flex flex-col gap-1">
          <label htmlFor="intake-field-title" className="text-sm text-[var(--lumi-text-secondary)]">
            标题表达式
          </label>
          <input
            id="intake-field-title"
            className={inputClass}
            value={titleExpr}
            onChange={(event) => setTitleExpr(event.target.value)}
          />
        </div>
        <button
          type="button"
          className={buttonClass}
          disabled={busy || label === '' || sampleText === ''}
          onClick={() => void saveSample()}
        >
          存样本
        </button>
      </div>
      {samples.map((sample) => (
        <div
          key={sample.id}
          data-intake-sample={sample.id}
          className="flex flex-wrap items-center gap-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-2"
        >
          <span className="text-sm text-[var(--lumi-text-primary)]">{sample.label}</span>
          <button
            type="button"
            className={secondaryButtonClass}
            disabled={busy}
            onClick={() => void previewWith(sample.id)}
          >
            预览映射
          </button>
          <button
            type="button"
            className={buttonClass}
            disabled={busy}
            onClick={() => void bindMapping()}
          >
            绑定此映射
          </button>
        </div>
      ))}
      {preview !== null && (
        <div
          data-intake-mapping-preview=""
          className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-2"
        >
          <StatusLine tone="info">
            预览 {preview.rows.length} / 共 {preview.total} 条（与生产同一映射管线）
          </StatusLine>
          {preview.rows.map((row, index) => (
            <p
              key={index}
              className="text-sm leading-relaxed text-[var(--lumi-text-secondary)]"
            >
              {String(row.id ?? '')} · {String(row.title ?? '')}
            </p>
          ))}
        </div>
      )}
      <Feedback notice={notice} error={error} />
    </div>
  )
}

// ---- 分页试抓台（有界：1..5 页；进行中可中止） -------------------------------

export function PaginationProbePanel(props: {
  sourceUuid: string | undefined
}): ReactElement {
  const [maxPages, setMaxPages] = useState('3')
  const [result, setResult] = useState<ProbeResult | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => () => abortRef.current?.abort(), [])

  async function run(): Promise<void> {
    if (props.sourceUuid === undefined) return
    const bounded = Math.min(5, Math.max(1, Math.trunc(Number(maxPages)) || 1))
    const controller = new AbortController()
    abortRef.current = controller
    setBusy(true)
    setError('')
    try {
      setResult(await new302Api.run(props.sourceUuid, bounded, controller.signal))
    } catch (err) {
      if (!isAbort(err)) setError(errorText(err))
    } finally {
      if (abortRef.current === controller) abortRef.current = null
      setBusy(false)
    }
  }

  function cancel(): void {
    abortRef.current?.abort()
  }

  const contractWarning =
    result !== null &&
    (result.gapPages > 0 || result.duplicatePages > 0)

  return (
    <div data-intake-probe-tools="" className="flex flex-col gap-3">
      <div className="flex items-end gap-2">
        <div className="flex flex-col gap-1">
          <label
            htmlFor="intake-probe-max-pages"
            className="text-sm text-[var(--lumi-text-secondary)]"
          >
            试抓页数上限（1..5）
          </label>
          <input
            id="intake-probe-max-pages"
            type="number"
            min={1}
            max={5}
            className={inputClass}
            value={maxPages}
            onChange={(event) => setMaxPages(event.target.value)}
          />
        </div>
        <button
          type="button"
          className={buttonClass}
          disabled={busy || props.sourceUuid === undefined}
          onClick={() => void run()}
        >
          开始受限试抓
        </button>
        {busy && (
          <button
            type="button"
            className={secondaryButtonClass}
            onClick={cancel}
            data-intake-probe-cancel=""
          >
            中止
          </button>
        )}
      </div>
      {result !== null && (
        <div
          data-intake-probe-result=""
          className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-2"
        >
          <StatusLine tone={contractWarning ? 'error' : 'ok'}>
            {result.pageCount} 页 / {result.itemCount} 条 · 停止原因{' '}
            {result.stopReason}
            {result.duplicatePages > 0 ? ` · 重复页 ${result.duplicatePages}` : ''}
            {result.gapPages > 0 ? ` · 缺页 ${result.gapPages}` : ''}
          </StatusLine>
          {result.pages.map((page, index) => (
            <p
              key={index}
              className="text-sm leading-relaxed text-[var(--lumi-text-secondary)]"
            >
              第 {page.page} 页：
              {page.error ? `失败（${page.error}）` : `${page.itemCount ?? 0} 条`} ·{' '}
              {page.url}
            </p>
          ))}
          <NoteText>
            试抓有硬上限（≤5 页），绝不自动无限抓取；页 URL 只显示形状，
            不显示参数值。
          </NoteText>
        </div>
      )}
      <Feedback notice="" error={error} />
    </div>
  )
}

// ---- 抓取变更预警（写暂停确认/恢复） -----------------------------------------

export function SchemaPausePanel(props: {
  sourceUuid: string | undefined
}): ReactElement {
  const [status, setStatus] = useState<{
    writePaused: boolean
    pauseReason: string | null
  } | null>(null)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const refresh = useCallback(async () => {
    if (props.sourceUuid === undefined) {
      setStatus(null)
      return
    }
    setError('')
    try {
      const current = await new306Api.status(props.sourceUuid)
      setStatus({
        writePaused: current.writePaused,
        pauseReason: current.pauseReason,
      })
    } catch (err) {
      setError(errorText(err))
    }
  }, [props.sourceUuid])

  useEffect(() => {
    void refresh()
  }, [refresh])

  async function resume(): Promise<void> {
    if (props.sourceUuid === undefined) return
    setBusy(true)
    setError('')
    setNotice('')
    try {
      const done = await new306Api.resume(props.sourceUuid)
      if (done.resumed === true) {
        setNotice('已恢复发布；新结构基线已确认。')
      } else {
        setNotice('该来源未处于写暂停。')
      }
      await refresh()
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div data-intake-pause-tools="" className="flex flex-col gap-3">
      {status !== null && (
        <StatusLine tone={status.writePaused ? 'error' : 'info'}>
          {status.writePaused
            ? `写暂停中：${status.pauseReason ?? '结构变更未确认'}`
            : '该来源未处于写暂停。'}
        </StatusLine>
      )}
      <button
        type="button"
        className={buttonClass}
        disabled={busy || props.sourceUuid === undefined}
        onClick={() => void resume()}
      >
        确认新映射并恢复发布
      </button>
      <NoteText>
        恢复会做一次受控探测：上游仍不可解析时保持暂停（409），绝不
        假装恢复。
      </NoteText>
      <Feedback notice={notice} error={error} />
    </div>
  )
}

// ---- 来源配额（每日条目数） ---------------------------------------------------

export function IntakeQuotaPanel(props: {
  sourceUuid: string | undefined
}): ReactElement {
  const [snapshot, setSnapshot] = useState<IntakeQuotaSnapshot | null>(null)
  const [maxItems, setMaxItems] = useState('50')
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const refresh = useCallback(async () => {
    if (props.sourceUuid === undefined) {
      setSnapshot(null)
      return
    }
    setError('')
    try {
      setSnapshot(await new307Api.get(props.sourceUuid))
    } catch (err) {
      setError(errorText(err))
    }
  }, [props.sourceUuid])

  useEffect(() => {
    void refresh()
  }, [refresh])

  async function saveLimit(): Promise<void> {
    if (props.sourceUuid === undefined) return
    setBusy(true)
    setError('')
    setNotice('')
    try {
      await new307Api.put(props.sourceUuid, Number(maxItems))
      await refresh()
      setNotice('每日条目配额已更新。')
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  async function removeQuota(): Promise<void> {
    if (props.sourceUuid === undefined) return
    setBusy(true)
    setError('')
    try {
      await new307Api.remove(props.sourceUuid)
      await refresh()
      setNotice('已取消配额；该来源不再按日限量。')
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  const parsedLimit = Math.trunc(Number(maxItems))

  return (
    <div data-intake-quota-tools="" className="flex flex-col gap-3">
      {snapshot !== null && (
        <StatusLine
          tone={
            snapshot.configured && snapshot.remaining === 0 ? 'error' : 'info'
          }
        >
          {snapshot.configured
            ? `今日已发布 ${snapshot.used} / 上限 ${snapshot.maxItemsPerDay}` +
              ` · 待处理 ${snapshot.pending} 条` +
              (snapshot.remaining === 0 ? ' · 已到限，请调整上限或等次日' : '')
            : snapshot.honestyNote}
        </StatusLine>
      )}
      <div className="flex items-end gap-2">
        <div className="flex flex-col gap-1">
          <label
            htmlFor="intake-quota-max-items"
            className="text-sm text-[var(--lumi-text-secondary)]"
          >
            每天最大条目数
          </label>
          <input
            id="intake-quota-max-items"
            type="number"
            min={1}
            className={inputClass}
            value={maxItems}
            onChange={(event) => setMaxItems(event.target.value)}
          />
        </div>
        <button
          type="button"
          className={buttonClass}
          disabled={
            busy ||
            props.sourceUuid === undefined ||
            Number.isNaN(parsedLimit) ||
            parsedLimit < 1
          }
          onClick={() => void saveLimit()}
        >
          设置配额
        </button>
        {snapshot !== null && snapshot.configured && (
          <button
            type="button"
            className={secondaryButtonClass}
            disabled={busy}
            onClick={() => void removeQuota()}
          >
            取消配额
          </button>
        )}
      </div>
      <Feedback notice={notice} error={error} />
    </div>
  )
}
