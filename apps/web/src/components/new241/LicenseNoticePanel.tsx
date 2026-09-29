/** NEW-249 资料引用许可证提示 — 按用户记录 / 来源明示显示引用限制，
 * 未知项明确标未知；输出固定附免责声明，不作法律保证。 */

import { useMutation } from '@tanstack/react-query'
import { useState } from 'react'
import { previewLicenseNotice, putLicenseRecord, type LicenseRecordView } from '../../api/new241'
import { Button } from '../ui/Button'
import { Skeleton } from '../ui/Skeleton'

const STATUS_LABELS: Record<LicenseRecordView['status'], string> = {
  recorded: '已记录（用户记录）',
  source_explicit: '已记录（来源明示）',
  explicit_undeclared: '来源有许可证字段但未声明具体文本',
  unknown: '未知',
}

export function LicenseNoticePanel() {
  const [targetRef, setTargetRef] = useState('')
  const [licenseText, setLicenseText] = useState('')
  const [infoSource, setInfoSource] = useState<'user_record' | 'source_explicit'>('user_record')
  const [note, setNote] = useState('')
  const [refsText, setRefsText] = useState('')
  const [preview, setPreview] = useState<Awaited<ReturnType<typeof previewLicenseNotice>> | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const recordMutation = useMutation({
    mutationFn: () => putLicenseRecord(targetRef, licenseText, infoSource, note),
    onSuccess: () => {
      setNotice('许可证记录已保存。')
      setLicenseText('')
      setNote('')
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : '记录保存失败'),
  })

  const previewMutation = useMutation({
    mutationFn: () =>
      previewLicenseNotice(
        refsText
          .split('\n')
          .map((line) => line.trim())
          .filter((line) => line !== ''),
      ),
    onSuccess: (result) => setPreview(result),
    onError: (error) => setNotice(error instanceof Error ? error.message : '提示预览失败'),
  })

  return (
    <section
      aria-label="资料引用许可证提示（NEW-249）"
      className="flex flex-col gap-2 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-3"
    >
      <div className="flex items-center gap-2">
        <h3 className="text-sm font-medium text-[var(--lumi-text-primary)]">资料引用许可证提示</h3>
        <span className="text-xs text-[var(--lumi-text-tertiary)]">NEW-249</span>
      </div>

      <div className="flex flex-col gap-1">
        <input
          aria-label="许可证记录目标 ref"
          value={targetRef}
          onChange={(event) => setTargetRef(event.target.value)}
          placeholder="资料 ref"
          className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-xs"
        />
        <input
          aria-label="许可证文本"
          value={licenseText}
          onChange={(event) => setLicenseText(event.target.value)}
          placeholder="许可证文本（如 CC BY-SA 4.0，可空 = 未声明）"
          className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-xs"
        />
        <div className="flex flex-wrap items-center gap-2">
          <label className="text-xs text-[var(--lumi-text-secondary)]">
            信息来源
            <select
              aria-label="许可证信息来源"
              value={infoSource}
              onChange={(event) => setInfoSource(event.target.value === 'source_explicit' ? 'source_explicit' : 'user_record')}
              className="ml-1 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1"
            >
              <option value="user_record">我自行记录</option>
              <option value="source_explicit">来源页面明示</option>
            </select>
          </label>
        </div>
        <input
          aria-label="许可证备注"
          value={note}
          onChange={(event) => setNote(event.target.value)}
          placeholder="备注（可空）"
          className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-xs"
        />
        <Button
          size="sm"
          variant="secondary"
          className="self-start"
          disabled={targetRef.trim() === '' || recordMutation.isPending}
          onClick={() => recordMutation.mutate()}
        >
          保存许可证记录
        </Button>
      </div>

      <div className="flex flex-col gap-1 border-t border-[var(--lumi-border)] pt-2">
        <textarea
          aria-label="汇编导出的资料 ref 列表（每行一个）"
          value={refsText}
          onChange={(event) => setRefsText(event.target.value)}
          placeholder="每行一个资料 ref，预览整份汇编的引用限制"
          rows={3}
          className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-xs"
        />
        <Button
          size="sm"
          variant="secondary"
          className="self-start"
          disabled={refsText.trim() === '' || previewMutation.isPending}
          onClick={() => previewMutation.mutate()}
        >
          预览引用限制提示
        </Button>
      </div>

      {previewMutation.isPending && <Skeleton className="h-10 w-full" />}
      {preview !== null && (
        <div className="flex flex-col gap-1 text-xs text-[var(--lumi-text-secondary)]" aria-label="许可证提示预览">
          {preview.items.map((item) => (
            <div key={item.targetRef}>
              <span className="text-[var(--lumi-text-primary)]">{item.targetRef}</span> —{' '}
              {STATUS_LABELS[item.status]}
              {item.licenseText !== null ? `：${item.licenseText}` : ''}
              {item.note !== '' ? `（${item.note}）` : ''}
            </div>
          ))}
          <p>未知项 {preview.unknownCount} 条。</p>
          <p className="text-[var(--lumi-text-tertiary)]">{preview.disclaimer}</p>
        </div>
      )}

      {notice !== null && (
        <p role="status" className="text-xs text-[var(--lumi-text-secondary)]">
          {notice}
        </p>
      )}
    </section>
  )
}
