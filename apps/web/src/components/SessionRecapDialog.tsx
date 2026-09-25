/** SessionRecapDialog — N080 阅读成果汇总（tools 入口，device-local）。
 *
 * 统计当前会话窗口（30 分钟）内**实际创建成功**的对象：批注 / 阅读问题
 * （N074）/ 知识卡片（N076）——事件由各自创建成功路径记录（lib/
 * session-recap），失败的尝试绝不计入。附可编辑的会话笔记（本机保存，
 * ≤2000 字符）。
 */

import { useEffect, useState } from 'react'
import {
  RECAP_NOTE_MAX_CHARS,
  loadRecapNote,
  saveRecapNote,
  sessionRecap,
  type SessionRecap as Recap,
} from '../lib/session-recap'
import { Button } from './ui/Button'
import { Dialog } from './ui/Dialog'

const COUNT_ITEMS: { key: keyof Omit<Recap, 'windowMinutes'>; label: string }[] = [
  { key: 'newAnnotations', label: '新建批注' },
  { key: 'questions', label: '记录问题' },
  { key: 'cards', label: '知识卡片' },
  { key: 'entriesTouched', label: '涉及文章' },
]

export function SessionRecapDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [recap, setRecap] = useState<Recap | null>(null)
  const [note, setNote] = useState('')
  const [noteInfo, setNoteInfo] = useState<string | null>(null)

  useEffect(() => {
    if (!open) return
    setRecap(sessionRecap(30))
    setNote(loadRecapNote())
    setNoteInfo(null)
  }, [open])

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="阅读成果"
      panelClassName="max-w-md"
      footer={
        <div className="flex w-full items-center gap-2">
          <span className="text-xs text-[var(--lumi-text-tertiary)]">
            统计最近 30 分钟 · 仅本设备
          </span>
          <div className="ml-auto">
            <Button variant="ghost" size="sm" onClick={onClose}>
              关闭
            </Button>
          </div>
        </div>
      }
    >
      <div className="flex flex-col gap-3" data-testid="session-recap">
        <dl className="grid grid-cols-2 gap-2">
          {COUNT_ITEMS.map((item) => (
            <div
              key={item.key}
              data-testid={`recap-${item.key}`}
              className="rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] px-3 py-2"
            >
              <dt className="text-xs text-[var(--lumi-text-secondary)]">{item.label}</dt>
              <dd className="text-xl font-semibold text-[var(--lumi-text-primary)]">
                {recap === null ? '—' : recap[item.key]}
              </dd>
            </div>
          ))}
        </dl>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-[var(--lumi-text-secondary)]">
            会话笔记（保存于本机，可随时修改）
          </span>
          <textarea
            value={note}
            onChange={(e) => {
              setNote(e.target.value)
              setNoteInfo(null)
            }}
            rows={4}
            maxLength={RECAP_NOTE_MAX_CHARS}
            aria-label="阅读成果会话笔记"
            data-testid="recap-note"
            className="w-full resize-y rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-3 py-2 text-sm text-[var(--lumi-text-primary)]"
          />
        </label>
        <div className="flex items-center justify-between gap-2">
          <span className="text-xs text-[var(--lumi-text-tertiary)]">
            {note.length}/{RECAP_NOTE_MAX_CHARS}
          </span>
          <Button
            size="sm"
            variant="secondary"
            disabled={note.length > RECAP_NOTE_MAX_CHARS}
            onClick={() => {
              const saved = saveRecapNote(note)
              setNoteInfo(saved ? '已保存（本机）' : '保存失败（存储不可用或超限）')
            }}
          >
            保存笔记
          </Button>
        </div>
        {noteInfo !== null && (
          <p role="status" className="text-xs text-[var(--lumi-text-secondary)]">{noteInfo}</p>
        )}
      </div>
    </Dialog>
  )
}
