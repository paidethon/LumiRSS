/** NEW-294 来源映射 / NEW-295 隐私遮罩 — 地址→个人来源映射 CRUD；
 * 显式字面遮罩 + 分享视图（原文私有，遮罩只在分享/导出路径生效）。 */

import { useCallback, useEffect, useState } from 'react'
import {
  addMask,
  deleteSourceMap,
  getShareView,
  listSourceMaps,
  putSourceMap,
  type ShareView,
  type SourceMap,
} from '../../api/new291'
import { NoteText, StatusLine, buttonClass, errorText, inputClass } from './panel'

export function SourceMapPanel() {
  const [maps, setMaps] = useState<SourceMap[]>([])
  const [fromAddr, setFromAddr] = useState('')
  const [label, setLabel] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const refresh = useCallback(async () => {
    try {
      setMaps(await listSourceMaps())
    } catch (err) {
      setError(errorText(err))
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  async function save(): Promise<void> {
    setBusy(true)
    setError('')
    try {
      await putSourceMap(fromAddr.trim(), label.trim())
      setFromAddr('')
      setLabel('')
      await refresh()
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div data-new291-source-maps="" className="flex flex-col gap-3">
      <label className="flex flex-col gap-1">
        <span className="text-sm text-[var(--lumi-text-secondary)]">发件地址（精确匹配，大小写不敏感）</span>
        <input type="text" className={inputClass} value={fromAddr} onChange={(e) => setFromAddr(e.target.value)} />
      </label>
      <label className="flex flex-col gap-1">
        <span className="text-sm text-[var(--lumi-text-secondary)]">个人资料来源名称</span>
        <input type="text" className={inputClass} value={label} onChange={(e) => setLabel(e.target.value)} />
      </label>
      <button type="button" className={buttonClass} disabled={busy || fromAddr.trim() === '' || label.trim() === ''} onClick={() => void save()}>
        保存映射
      </button>
      <ul className="flex flex-col gap-1">
        {maps.map((m) => (
          <li key={m.fromAddr} className="flex items-center gap-2 text-sm text-[var(--lumi-text-primary)]">
            <span className="flex-1">
              {m.fromAddr} → {m.sourceLabel}
            </span>
            <button
              type="button"
              className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2 py-0.5 text-sm hover:bg-[var(--lumi-surface-hover)]"
              onClick={() => {
                void deleteSourceMap(m.fromAddr).then(refresh).catch((err) => setError(errorText(err)))
              }}
            >
              取消映射
            </button>
          </li>
        ))}
      </ul>
      <NoteText>只对映射之后导入的邮件自动归源，不追溯改写已入库条目。</NoteText>
      {error !== '' && <StatusLine tone="error">{error}</StatusLine>}
    </div>
  )
}

const MASK_KINDS = [
  { value: 'address', label: '地址' },
  { value: 'signature', label: '签名' },
  { value: 'custom', label: '选中文字' },
]

export function MaskPanel({ materialId }: { materialId: string }) {
  const [kind, setKind] = useState('address')
  const [value, setValue] = useState('')
  const [share, setShare] = useState<ShareView | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const refresh = useCallback(async () => {
    try {
      setShare(await getShareView(materialId))
    } catch (err) {
      setError(errorText(err))
    }
  }, [materialId])

  useEffect(() => {
    void refresh()
  }, [refresh])

  async function add(): Promise<void> {
    setBusy(true)
    setError('')
    try {
      await addMask(materialId, kind, value)
      setValue('')
      await refresh()
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div data-new291-masks="" className="flex flex-col gap-3">
      <label className="flex flex-col gap-1">
        <span className="text-sm text-[var(--lumi-text-secondary)]">遮罩类型</span>
        <select className={inputClass} value={kind} onChange={(e) => setKind(e.target.value)}>
          {MASK_KINDS.map((k) => (
            <option key={k.value} value={k.value}>
              {k.label}
            </option>
          ))}
        </select>
      </label>
      <label className="flex flex-col gap-1">
        <span className="text-sm text-[var(--lumi-text-secondary)]">要隐藏的字面文本（必须出现在正文中）</span>
        <input type="text" className={inputClass} value={value} onChange={(e) => setValue(e.target.value)} />
      </label>
      <button type="button" className={buttonClass} disabled={busy || value.trim() === ''} onClick={() => void add()}>
        添加遮罩（分享时隐藏）
      </button>
      {share !== null && (
        <div data-new291-share-view="" className="flex flex-col gap-1">
          <StatusLine tone="info">分享视图（原文仍私有保存，遮罩 {share.masks.length} 处）</StatusLine>
          <pre className="whitespace-pre-wrap rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-2 text-sm leading-relaxed text-[var(--lumi-text-secondary)]">
            {share.maskedBodyText}
          </pre>
          <NoteText>{share.honestyNote}</NoteText>
        </div>
      )}
      {error !== '' && <StatusLine tone="error">{error}</StatusLine>}
    </div>
  )
}
