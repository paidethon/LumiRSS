/** NEW-314 快照文字检索层工具 — 组合面板（两级情境展开）。
 *
 * 对已保存的快照构建可查找文本层（构建是纯读 + 派生表写入，原快照
 * 字节不变），搜索命中给出 (seq, 标题锚) 供定位。服务真源：
 * routers/new314_snapshot_text_layer.py。
 */

import { useState } from 'react'
import {
  buildTextLayer,
  searchTextLayer,
  type TextLayerHit,
} from '../../api/new311'
import { Button } from '../ui/Button'
import {
  NoteText,
  StatusLine,
  SubSection,
  errorText,
  inputClass,
} from './parts'

export function New311SnapshotTextTools() {
  const [open, setOpen] = useState(false)
  return (
    <section data-new311-snapshot-text-tools="">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="min-h-8 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-2.5 text-sm font-medium text-[var(--lumi-text-primary)] hover:bg-[var(--lumi-surface-hover)]"
      >
        快照文字检索（{open ? '收起' : '展开'}）
      </button>
      {open && (
        <div className="mt-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] p-3">
          <TextLayerSection />
        </div>
      )}
    </section>
  )
}

function TextLayerSection() {
  const [assetUuid, setAssetUuid] = useState('')
  const [query, setQuery] = useState('')
  const [hits, setHits] = useState<TextLayerHit[] | null>(null)
  const [blockCount, setBlockCount] = useState<number | null>(null)
  const [status, setStatus] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function build() {
    setBusy(true)
    setError(null)
    setStatus(null)
    setHits(null)
    try {
      const done = await buildTextLayer(assetUuid.trim())
      setBlockCount(done.blockCount)
      setStatus(`文字层已构建（${done.blockCount} 块），原快照保持不变。`)
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  async function search() {
    setBusy(true)
    setError(null)
    setStatus(null)
    try {
      const done = await searchTextLayer(assetUuid.trim(), query.trim())
      setHits(done.hits)
      setStatus(
        done.hits.length === 0 ? '没有命中。' : `命中 ${done.hitCount} 处（最多显示前若干条）。`,
      )
    } catch (err) {
      setHits(null)
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <SubSection id="text-layer" label="快照文字检索层">
      <label className="flex flex-col gap-1">
        <span className="text-xs text-[var(--lumi-text-secondary)]">快照 uuid</span>
        <input
          type="text"
          value={assetUuid}
          onChange={(e) => setAssetUuid(e.target.value)}
          aria-label="快照标识"
          className={inputClass}
        />
      </label>
      <Button variant="secondary" size="sm" disabled={busy || assetUuid.trim() === ''} onClick={() => void build()}>
        构建文字层
      </Button>
      {blockCount !== null && (
        <div className="flex flex-wrap items-end gap-2">
          <label className="flex flex-1 flex-col gap-1">
            <span className="text-xs text-[var(--lumi-text-secondary)]">在快照文字层中查找</span>
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              aria-label="文字层搜索词"
              className={inputClass}
            />
          </label>
          <Button variant="primary" size="sm" disabled={busy || query.trim() === ''} onClick={() => void search()}>
            查找
          </Button>
        </div>
      )}
      {status && <StatusLine tone="ok">{status}</StatusLine>}
      {error && <StatusLine tone="error">{error}</StatusLine>}
      {hits !== null && hits.length > 0 && (
        <ul className="ml-4 list-disc text-xs leading-relaxed text-[var(--lumi-text-secondary)]" data-new311-text-layer-hits="">
          {hits.slice(0, 8).map((hit) => (
            <li key={hit.seq}>
              [{hit.seq}] {hit.anchor !== '' ? `${hit.anchor} · ` : ''}
              {hit.text}
            </li>
          ))}
        </ul>
      )}
      <NoteText>文字层是派生数据，可随时重建；快照本体字节与 sha256 不变。</NoteText>
    </SubSection>
  )
}
