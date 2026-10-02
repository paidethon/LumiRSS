/** NEW-381..390 长期保存与格式互通 —— 组合面板。
 *
 * 数据全部来自 BFF 真实端点；诚实口径原样展示（不支持字段、缺卷、
 * missing 对账、口令即用即弃）。全部二级情境展开：折叠 = 不挂载 =
 * 零查询。输入都有可见标签；视觉只用既有 --lumi-* 语义令牌。
 */

import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  buildIndexCatalog,
  compareFormats,
  confirmReconciliation,
  createEncryptedExport,
  createJsonFeed,
  createOfflineSite,
  exportVolumes,
  importRis,
  importZoteroRdf,
  listComparisons,
  listEncryptedExports,
  listFeedExports,
  listIndexExports,
  listOfflineSites,
  listReconciliations,
  listVolumeSets,
  previewRis,
  previewZoteroRdf,
  verifyEncryptedExport,
  type BibPreview,
} from '../../api/new381'
import { Button } from '../ui/Button'
import {
  NoteText,
  StatusLine,
  SubSection,
  actionButtonClass,
  errorText,
  inputClass,
} from './parts'

// ---- NEW-381/382 书目导入（Zotero RDF / RIS 预览 → 确认） -------------------

function BibPreviewView({ preview }: { preview: BibPreview }) {
  return (
    <div className="flex flex-col gap-2" data-n381-bib-preview="">
      <StatusLine tone="info">
        共 {preview.total} 条；重复 {preview.duplicates} 条；不支持字段：
        {preview.unsupportedFields.length > 0 ? preview.unsupportedFields.join('、') : '无'}
      </StatusLine>
      <ul className="flex flex-col gap-1">
        {preview.items.slice(0, 20).map((item) => (
          <li key={`${item.externalId}-${item.title}`} className="text-sm text-[var(--lumi-text-primary)]">
            <span className="font-medium">{item.title}</span>
            {' · '}
            {item.externalId}
            {item.creators.length > 0 && ` · ${item.creators.join('；')}`}
            {item.pubYear && ` · ${item.pubYear}`}
            {item.duplicate && (
              <span className="ml-1 text-[var(--lumi-warning)]">
                （重复：{item.duplicateReason === 'external_id' ? '同一引用标识' : '标题+年份'}）
              </span>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}

export function BibImportSection() {
  const queryClient = useQueryClient()
  const [content, setContent] = useState('')
  const [preview, setPreview] = useState<BibPreview | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<string | null>(null)

  async function runPreview(kind: 'zotero' | 'ris') {
    setBusy(true)
    setError(null)
    setResult(null)
    try {
      setPreview(kind === 'zotero' ? await previewZoteroRdf(content) : await previewRis(content))
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }
  async function runImport(kind: 'zotero' | 'ris') {
    setBusy(true)
    setError(null)
    try {
      const outcome = kind === 'zotero' ? await importZoteroRdf(content) : await importRis(content)
      setResult(
        `导入完成：新增 ${outcome.imported}，重复跳过 ${outcome.duplicates}，失败 ${outcome.failed}。`,
      )
      setPreview(null)
      await queryClient.invalidateQueries({ queryKey: ['n381-records'] })
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="flex flex-col gap-2" data-n381-bib-import="">
      <label htmlFor="n381-bib-content" className="text-sm font-medium text-[var(--lumi-text-primary)]">
        书目文件内容（Zotero RDF 或 RIS 文本）
      </label>
      <textarea
        id="n381-bib-content"
        data-testid="n381-bib-content"
        value={content}
        onChange={(event) => setContent(event.target.value)}
        rows={5}
        className={inputClass}
      />
      <div className="flex gap-2">
        <Button variant="secondary" disabled={busy || !content.trim()} onClick={() => void runPreview('zotero')}>
          预览字段映射（Zotero RDF）
        </Button>
        <Button variant="secondary" disabled={busy || !content.trim()} onClick={() => void runPreview('ris')}>
          预览（RIS）
        </Button>
        <Button variant="secondary" disabled={busy || !content.trim()} onClick={() => void runImport('zotero')}>
          导入（Zotero RDF）
        </Button>
        <Button variant="secondary" disabled={busy || !content.trim()} onClick={() => void runImport('ris')}>
          导入（RIS）
        </Button>
      </div>
      {error !== null && <StatusLine tone="error">{error}</StatusLine>}
      {result !== null && <StatusLine tone="ok">{result}</StatusLine>}
      {preview !== null && <BibPreviewView preview={preview} />}
      <NoteText>
        原始引用标识（Zotero item key / RIS AN）原样保留；重复资料默认跳过，不覆盖既有值。
        导出为 RIS 可用「索引与格式」区的往返校验。
      </NoteText>
    </div>
  )
}

// ---- NEW-383 离线站点 / NEW-384 JSON Feed -----------------------------------

export function OfflineSiteSection() {
  const queryClient = useQueryClient()
  const query = useQuery({ queryKey: ['n381-offline-sites'], queryFn: listOfflineSites })
  const [bibIds, setBibIds] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  if (query.isPending) return <StatusLine tone="info">加载中…</StatusLine>
  if (query.isError) return <StatusLine tone="error">{errorText(query.error)}</StatusLine>
  const sites = query.data.sites
  async function create() {
    setBusy(true)
    setError(null)
    try {
      await createOfflineSite(
        bibIds.split(/[\s,]+/).filter((ref) => ref.startsWith('bib-')),
        [],
      )
      await queryClient.invalidateQueries({ queryKey: ['n381-offline-sites'] })
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="flex flex-col gap-2" data-n381-offline="">
      {sites.length === 0 ? (
        <StatusLine tone="info">还没有离线资料集。</StatusLine>
      ) : (
        <ul className="flex flex-col gap-1">
          {sites.slice(0, 10).map((site) => (
            <li key={site.id} className="text-sm text-[var(--lumi-text-primary)]">
              {site.createdAt} · {site.itemCount} 条 · 违规 {site.violationCount} ·{' '}
              {site.missing.length > 0 ? `缺失 ${site.missing.length}` : '无缺失'}
            </li>
          ))}
        </ul>
      )}
      <label htmlFor="n381-offline-bibids" className="text-sm font-medium text-[var(--lumi-text-primary)]">
        选中的书目记录 id（空格分隔；只包含你选中的内容）
      </label>
      <input
        id="n381-offline-bibids"
        data-testid="n381-offline-bibids"
        value={bibIds}
        onChange={(event) => setBibIds(event.target.value)}
        className={inputClass}
      />
      <Button variant="secondary" disabled={busy} onClick={() => void create()}>
        生成离线资料集
      </Button>
      {error !== null && <StatusLine tone="error">{error}</StatusLine>}
      <NoteText>
        静态站点无需服务端即可打开；包内链接自洽，越界引用被移除并如实记账；未选内容不进包。
      </NoteText>
    </div>
  )
}

export function JsonFeedSection() {
  const queryClient = useQueryClient()
  const query = useQuery({ queryKey: ['n381-feed-exports'], queryFn: listFeedExports })
  const [withBib, setWithBib] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState<string | null>(null)
  if (query.isPending) return <StatusLine tone="info">加载中…</StatusLine>
  if (query.isError) return <StatusLine tone="error">{errorText(query.error)}</StatusLine>
  async function create() {
    setBusy(true)
    setError(null)
    try {
      const scopes = withBib ? ['clips', 'bib'] : ['clips']
      const feed = await createJsonFeed(scopes)
      setDone(`已生成 JSON Feed 1.1（本响应内共 ${feed.itemCount} 条）。`)
      await queryClient.invalidateQueries({ queryKey: ['n381-feed-exports'] })
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="flex flex-col gap-2" data-n381-jsonfeed="">
      <label className="flex items-center gap-2 text-sm text-[var(--lumi-text-primary)]">
        <input type="checkbox" checked={withBib} onChange={(event) => setWithBib(event.target.checked)} />
        包含书目记录（否则仅剪藏）
      </label>
      <Button variant="secondary" disabled={busy} onClick={() => void create()}>
        生成 JSON Feed 导出
      </Button>
      {done !== null && <StatusLine tone="ok">{done}</StatusLine>}
      {error !== null && <StatusLine tone="error">{error}</StatusLine>}
      <ul className="flex flex-col gap-1">
        {query.data.exports.slice(0, 5).map((entry) => (
          <li key={entry.id} className="text-sm text-[var(--lumi-text-primary)]">
            {entry.createdAt} · 范围 {entry.scope} · 剪藏 {entry.clipCount} / 书目 {entry.bibCount}
          </li>
        ))}
      </ul>
      <NoteText>导出附带包含字段清单与授权范围说明（只含本人资料，不含他人数据与凭据）。</NoteText>
    </div>
  )
}

// ---- NEW-386 格式对照 -------------------------------------------------------

export function FormatCompareSection() {
  const queryClient = useQueryClient()
  const query = useQuery({ queryKey: ['n381-comparisons'], queryFn: listComparisons })
  const [itemIds, setItemIds] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [summary, setSummary] = useState<string | null>(null)
  if (query.isPending) return <StatusLine tone="info">加载中…</StatusLine>
  if (query.isError) return <StatusLine tone="error">{errorText(query.error)}</StatusLine>
  async function run() {
    setBusy(true)
    setError(null)
    try {
      const ids = itemIds.split(/[\s,]+/).filter((ref) => ref.startsWith('bib-'))
      const outcome = await compareFormats(ids)
      const lines = outcome.items.map((item) => {
        const parts = Object.entries(item.formats).map(([format, view]) => {
          const lost = view.lostFields.length > 0 ? `丢 ${view.lostFields.join('/')}` : '无损失'
          return `${format}：${lost}`
        })
        return `${item.title} → ${parts.join('；')}`
      })
      setSummary(lines.join('\n') || '没有可对照的资料。')
      await queryClient.invalidateQueries({ queryKey: ['n381-comparisons'] })
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="flex flex-col gap-2" data-n381-compare="">
      <label htmlFor="n381-compare-ids" className="text-sm font-medium text-[var(--lumi-text-primary)]">
        要对照的书目记录 id（空格分隔）
      </label>
      <input
        id="n381-compare-ids"
        data-testid="n381-compare-ids"
        value={itemIds}
        onChange={(event) => setItemIds(event.target.value)}
        className={inputClass}
      />
      <Button variant="secondary" disabled={busy} onClick={() => void run()}>
        对照 Markdown / HTML / 纯文本
      </Button>
      {summary !== null && (
        <pre data-testid="n381-compare-summary" className="whitespace-pre-wrap text-sm text-[var(--lumi-text-primary)]">
          {summary}
        </pre>
      )}
      {error !== null && <StatusLine tone="error">{error}</StatusLine>}
      <NoteText>对照结果逐字段标注 kept / changed / lost；源记录本就没有的字段标 na，不算损失。</NoteText>
    </div>
  )
}

// ---- NEW-387 加密导出（口令即用即弃） ---------------------------------------

export function EncryptedExportSection() {
  const queryClient = useQueryClient()
  const query = useQuery({ queryKey: ['n381-encrypted'], queryFn: listEncryptedExports })
  const [itemIds, setItemIds] = useState('')
  const [passphrase, setPassphrase] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState<string | null>(null)
  if (query.isPending) return <StatusLine tone="info">加载中…</StatusLine>
  if (query.isError) return <StatusLine tone="error">{errorText(query.error)}</StatusLine>
  async function create() {
    setBusy(true)
    setError(null)
    setDone(null)
    try {
      const ids = itemIds.split(/[\s,]+/).filter((ref) => ref.startsWith('bib-'))
      const outcome = await createEncryptedExport(ids, passphrase)
      // 创建即做一次解密校验；随后用回传校验再验一次（口令即用即弃）
      const verify = await verifyEncryptedExport(outcome.payloadBase64, passphrase)
      setDone(
        `已生成加密包 ${outcome.id}（${outcome.itemCount} 条）；服务端解密校验：${outcome.decryptVerified ? '通过' : '未通过'}；回传校验：${verify.decryptVerified ? '通过' : '未通过'}。口令未被保存。`,
      )
      setPassphrase('')
      await queryClient.invalidateQueries({ queryKey: ['n381-encrypted'] })
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="flex flex-col gap-2" data-n381-encrypted="">
      <label htmlFor="n381-enc-ids" className="text-sm font-medium text-[var(--lumi-text-primary)]">
        要打包的书目记录 id（空格分隔）
      </label>
      <input
        id="n381-enc-ids"
        data-testid="n381-enc-ids"
        value={itemIds}
        onChange={(event) => setItemIds(event.target.value)}
        className={inputClass}
      />
      <label htmlFor="n381-enc-pass" className="text-sm font-medium text-[var(--lumi-text-primary)]">
        本次口令（仅本次使用；不保存、不写日志）
      </label>
      <input
        id="n381-enc-pass"
        data-testid="n381-enc-pass"
        type="password"
        autoComplete="new-password"
        value={passphrase}
        onChange={(event) => setPassphrase(event.target.value)}
        className={inputClass}
      />
      <Button variant="secondary" disabled={busy} onClick={() => void create()}>
        生成加密包并校验
      </Button>
      {done !== null && <StatusLine tone="ok">{done}</StatusLine>}
      {error !== null && <StatusLine tone="error">{error}</StatusLine>}
      <ul className="flex flex-col gap-1">
        {query.data.exports.length === 0 ? (
          <StatusLine tone="info">还没有加密导出记录。</StatusLine>
        ) : (
          query.data.exports.slice(0, 5).map((entry) => (
            <li key={entry.id} className="text-sm text-[var(--lumi-text-primary)]">
              {entry.createdAt} · {entry.itemCount} 条 · {entry.cipher} · 解密校验
              {entry.decryptVerified ? '通过' : '未通过'}
            </li>
          ))
        )}
      </ul>
      <NoteText>
        PBKDF2-HMAC-SHA256(600k) + AES-256-GCM（密码库原语，不自造算法）；台账只存参数与摘要，口令与包本体都不保存。
      </NoteText>
    </div>
  )
}

// ---- NEW-388 索引导出 -------------------------------------------------------

export function IndexExportSection() {
  const query = useQuery({ queryKey: ['n381-index'], queryFn: listIndexExports })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [catalog, setCatalog] = useState<{ recordCount: number; catalogSha256: string; note: string } | null>(null)
  if (query.isPending) return <StatusLine tone="info">加载中…</StatusLine>
  if (query.isError) return <StatusLine tone="error">{errorText(query.error)}</StatusLine>
  async function build() {
    setBusy(true)
    setError(null)
    try {
      const built = await buildIndexCatalog()
      setCatalog(built)
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="flex flex-col gap-2" data-n381-index="">
      <Button variant="secondary" disabled={busy} onClick={() => void build()}>
        生成索引导出
      </Button>
      {catalog !== null && (
        <StatusLine tone="ok" testId="catalog">
          {catalog.recordCount} 条 · 目录校验值 {catalog.catalogSha256.slice(0, 16)}… · {catalog.note}
        </StatusLine>
      )}
      {error !== null && <StatusLine tone="error">{error}</StatusLine>}
      <ul className="flex flex-col gap-1">
        {query.data.exports.slice(0, 5).map((entry) => (
          <li key={entry.id} className="text-sm text-[var(--lumi-text-primary)]">
            {entry.createdAt} · {entry.recordCount} 条 · 标签 {entry.tagCount} / 来源 {entry.sourceCount}
          </li>
        ))}
      </ul>
      <NoteText>只含资料目录、标签、来源与逐条校验值；不含摘要或全文。</NoteText>
    </div>
  )
}

// ---- NEW-389 分卷 -----------------------------------------------------------

export function VolumeSection() {
  const queryClient = useQueryClient()
  const query = useQuery({ queryKey: ['n381-volumes'], queryFn: listVolumeSets })
  const [itemIds, setItemIds] = useState('')
  const [capKiB, setCapKiB] = useState(64)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState<string | null>(null)
  if (query.isPending) return <StatusLine tone="info">加载中…</StatusLine>
  if (query.isError) return <StatusLine tone="error">{errorText(query.error)}</StatusLine>
  async function run() {
    setBusy(true)
    setError(null)
    try {
      const ids = itemIds.split(/[\s,]+/).filter((ref) => ref.startsWith('bib-'))
      const split = await exportVolumes(ids, capKiB * 1024)
      setDone(
        `卷集 ${split.setManifest.setId}：共 ${split.setManifest.volumeCount} 卷 / ${split.setManifest.itemCount} 条。`,
      )
      await queryClient.invalidateQueries({ queryKey: ['n381-volumes'] })
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="flex flex-col gap-2" data-n381-volumes="">
      <label htmlFor="n381-vol-ids" className="text-sm font-medium text-[var(--lumi-text-primary)]">
        要分卷的书目记录 id（空格分隔；留空 = 全部）
      </label>
      <input
        id="n381-vol-ids"
        data-testid="n381-vol-ids"
        value={itemIds}
        onChange={(event) => setItemIds(event.target.value)}
        className={inputClass}
      />
      <label htmlFor="n381-vol-cap" className="text-sm font-medium text-[var(--lumi-text-primary)]">
        单卷上限（KiB，8–1024）
      </label>
      <input
        id="n381-vol-cap"
        data-testid="n381-vol-cap"
        type="number"
        min={8}
        max={1024}
        value={capKiB}
        onChange={(event) => setCapKiB(Number(event.target.value) || 64)}
        className={inputClass}
      />
      <Button variant="secondary" disabled={busy} onClick={() => void run()}>
        生成分卷
      </Button>
      {done !== null && <StatusLine tone="ok">{done}</StatusLine>}
      {error !== null && <StatusLine tone="error">{error}</StatusLine>}
      <ul className="flex flex-col gap-1">
        {query.data.sets.slice(0, 5).map((set) => (
          <li key={set.setId} className="text-sm text-[var(--lumi-text-primary)]">
            {set.createdAt} · {set.setId} · {set.volumeCount} 卷 / {set.itemCount} 条
          </li>
        ))}
      </ul>
      <NoteText>每卷带清单；导入时缺卷即拒绝（409 + 缺失报告），绝不默默少导。</NoteText>
    </div>
  )
}

// ---- NEW-390 对账 -----------------------------------------------------------

export function ReconciliationSection() {
  const queryClient = useQueryClient()
  const query = useQuery({ queryKey: ['n381-reconciliations'], queryFn: listReconciliations })
  const [busyId, setBusyId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  if (query.isPending) return <StatusLine tone="info">加载中…</StatusLine>
  if (query.isError) return <StatusLine tone="error">{errorText(query.error)}</StatusLine>
  async function confirm(id: string, externalId: string) {
    setBusyId(`${id}:${externalId}`)
    setError(null)
    try {
      await confirmReconciliation(id, [externalId])
      await queryClient.invalidateQueries({ queryKey: ['n381-reconciliations'] })
    } catch (err) {
      setError(errorText(err))
    } finally {
      setBusyId(null)
    }
  }
  return (
    <div className="flex flex-col gap-3" data-n381-reconciliations="">
      {query.data.reconciliations.length === 0 ? (
        <StatusLine tone="info">暂无对账单（分卷完整导入后自动生成）。</StatusLine>
      ) : (
        query.data.reconciliations.slice(0, 5).map((recon) => (
          <div key={recon.id} className="flex flex-col gap-2" data-n381-reconciliation={recon.id}>
            <StatusLine tone="info">
              {recon.id} · {recon.source} · 待确认 {recon.pendingCount}（新增 {recon.counts.added} /
              对应 {recon.counts.matched} / 失败 {recon.counts.failed} / 丢失 {recon.counts.missing}）
              {recon.status === 'completed' && ' · 已完成'}
            </StatusLine>
            <ul className="flex flex-col gap-1">
              {recon.results.slice(0, 20).map((entry) => {
                const confirmed = recon.confirmed.includes(entry.externalId)
                return (
                  <li key={`${entry.externalId}-${entry.status}`} className="flex items-center gap-2 text-sm text-[var(--lumi-text-primary)]">
                    <span className="min-w-0 flex-1 truncate">
                      {entry.title || entry.externalId} ·{' '}
                      {entry.status === 'added' && '新增'}
                      {entry.status === 'matched' && '对应既有'}
                      {entry.status === 'failed' && `失败：${entry.detail}`}
                      {entry.status === 'missing' && '丢失（清单有、导入结果无）'}
                    </span>
                    {confirmed ? (
                      <StatusLine tone="ok">已确认</StatusLine>
                    ) : (
                      <button
                        type="button"
                        className={actionButtonClass}
                        disabled={busyId === `${recon.id}:${entry.externalId}`}
                        onClick={() => void confirm(recon.id, entry.externalId)}
                      >
                        确认这条
                      </button>
                    )}
                  </li>
                )
              })}
            </ul>
          </div>
        ))
      )}
      {error !== null && <StatusLine tone="error">{error}</StatusLine>}
      <NoteText>逐条确认，无一键全收；missing 与 failed 分开列（一个没到，一个到了但失败）。</NoteText>
    </div>
  )
}

/** 组合入口：设置 → 数据控制 → 长期保存与格式互通。 */
export function PreservationCenter() {
  return (
    <div className="flex flex-col gap-3" data-n381-center="">
      <SubSection id="bib-import" label="书目导入（Zotero RDF / RIS）">
        <BibImportSection />
      </SubSection>
      <SubSection id="offline-site" label="离线 HTML 资料集">
        <OfflineSiteSection />
      </SubSection>
      <SubSection id="json-feed" label="JSON Feed 个人导出">
        <JsonFeedSection />
      </SubSection>
      <SubSection id="format-compare" label="保存格式对照预览">
        <FormatCompareSection />
      </SubSection>
      <SubSection id="encrypted" label="个人资料包加密导出">
        <EncryptedExportSection />
      </SubSection>
      <SubSection id="index-export" label="个人索引导出">
        <IndexExportSection />
      </SubSection>
      <SubSection id="volumes" label="分卷导出">
        <VolumeSection />
      </SubSection>
      <SubSection id="reconciliations" label="迁移结果逐项对账">
        <ReconciliationSection />
      </SubSection>
    </div>
  )
}
