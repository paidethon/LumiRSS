/** ShortcutsSettingsSection — P13 快捷键分配 UI（设置中心「快捷键」页）。
 *
 * 数据单一真源：SHORTCUT_ACTIONS + DEFAULT_BINDINGS + effectiveShortcuts
 * （与「?」帮助弹窗、全局按键处理器共用，不复制文案/绑定）。
 * 引擎复用 lib/custom-shortcuts（F037 纯逻辑核心，此前无 UI 调用方）：
 * - 修改 → 捕获模式：window 捕获阶段监听下一个 keydown（Esc 取消、
 *   Backspace/Delete 清除自定义回退默认）；
 * - 冲突 → detectConflict（按生效表 = 默认 + 覆盖）→ 显式「覆盖」确认；
 * - 保留组合（浏览器必备）→ assignShortcut 拒绝并提示；
 * - 导入/导出：JSON 文件（lumirss-shortcuts.json），逐条校验
 *   （未知动作 / 保留组合跳过），汇总「已应用 X 项，跳过 Y 项」。
 *
 * 捕获监听挂在 window **捕获阶段** 并 stopPropagation：先于全局快捷键
 * 处理器（bubble）与设置弹窗的 Escape 关闭，捕获期间按键不被二次消费。
 * IME 组合中的按键一律忽略（shouldIgnoreKeyEvent）。 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { Download, Upload } from 'lucide-react'
import { Button } from '../ui/Button'
import {
  DEFAULT_BINDINGS,
  SHORTCUT_ACTIONS,
  effectiveShortcuts,
  eventToCombo,
  shouldIgnoreKeyEvent,
} from '../../lib/keyboard-shortcuts'
import {
  assignShortcut,
  detectConflict,
  formatCombo,
  isReservedCombo,
  loadCustomShortcuts,
  normalizeCombo,
  resetShortcut,
  saveCustomShortcuts,
} from '../../lib/custom-shortcuts'

/** 修饰键单独按下不构成组合（等待主键）。 */
const MODIFIER_ONLY_KEYS = new Set(['Shift', 'Control', 'Alt', 'Meta'])

function actionLabel(actionId: string): string {
  return SHORTCUT_ACTIONS.find((a) => a.id === actionId)?.action ?? actionId
}

interface PendingConflict {
  actionId: string
  combo: string
  conflictWith: string
}

export function ShortcutsSettingsSection() {
  const [custom, setCustom] = useState<Record<string, string>>(() =>
    loadCustomShortcuts(),
  )
  const customRef = useRef(custom)
  const [capturing, setCapturing] = useState<string | null>(null)
  const [pending, setPending] = useState<PendingConflict | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const noticeTimerRef = useRef<number | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const applyCustom = useCallback(
    (next: Record<string, string>) => {
      customRef.current = next
      setCustom(next)
      saveCustomShortcuts(next)
    },
    [],
  )

  const flash = useCallback((text: string) => {
    setNotice(text)
    if (noticeTimerRef.current !== null) window.clearTimeout(noticeTimerRef.current)
    noticeTimerRef.current = window.setTimeout(() => setNotice(null), 4000)
  }, [])

  useEffect(
    () => () => {
      if (noticeTimerRef.current !== null) window.clearTimeout(noticeTimerRef.current)
    },
    [],
  )

  // 捕获模式：window 捕获阶段消费下一个组合键
  useEffect(() => {
    if (capturing === null) return
    const onKey = (e: KeyboardEvent) => {
      // P13：IME 组合中的按键不是快捷键输入
      if (shouldIgnoreKeyEvent(e)) return
      // 保留焦点导航（Tab 穿透，不进入捕获）
      if (e.key === 'Tab') return
      // 修饰键单独按下：等待主键
      if (MODIFIER_ONLY_KEYS.has(e.key)) return
      e.preventDefault()
      e.stopPropagation()

      if (e.key === 'Escape') {
        setCapturing(null)
        flash('已取消，绑定未修改')
        return
      }
      if (e.key === 'Backspace' || e.key === 'Delete') {
        applyCustom(resetShortcut(customRef.current, capturing))
        setCapturing(null)
        flash('已清除自定义，恢复默认绑定')
        return
      }
      const combo = normalizeCombo(eventToCombo(e))
      if (combo === null) return
      // 冲突按生效表（默认 + 覆盖）检测——与实际按键解析同一视野
      const effective = { ...DEFAULT_BINDINGS, ...customRef.current }
      const { conflictWith } = detectConflict(effective, capturing, combo)
      if (conflictWith !== null) {
        setPending({ actionId: capturing, combo, conflictWith })
        setCapturing(null)
        return
      }
      const { custom: next, error } = assignShortcut(customRef.current, capturing, combo)
      setCapturing(null)
      if (error === 'reserved') {
        flash(`「${formatCombo(combo)}」是浏览器保留组合，无法分配`)
        return
      }
      if (error !== null) return
      applyCustom(next)
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [capturing, applyCustom, flash])

  const confirmOverwrite = () => {
    if (pending === null) return
    const { actionId, combo, conflictWith } = pending
    const { custom: assigned, error } = assignShortcut(customRef.current, actionId, combo, {
      overwrite: true,
    })
    setPending(null)
    if (error !== null) return
    // 被覆盖方：移除其自定义覆盖（若有）→ 展示回退到默认绑定
    const next =
      conflictWith in assigned ? resetShortcut(assigned, conflictWith) : assigned
    applyCustom(next)
    flash(`已覆盖：「${actionLabel(conflictWith)}」回退到默认绑定`)
  }

  const exportShortcuts = () => {
    const payload = JSON.stringify({ version: 1, shortcuts: customRef.current }, null, 2)
    const blob = new Blob([payload], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = 'lumirss-shortcuts.json'
    anchor.click()
    URL.revokeObjectURL(url)
    flash('已导出 lumirss-shortcuts.json')
  }

  const importShortcuts = useCallback(
    async (file: File) => {
      let parsed: unknown
      try {
        parsed = JSON.parse(await file.text())
      } catch {
        flash('导入失败：不是有效的 JSON 文件')
        return
      }
      const entries =
        parsed !== null &&
        typeof parsed === 'object' &&
        !Array.isArray(parsed) &&
        typeof (parsed as { shortcuts?: unknown }).shortcuts === 'object' &&
        (parsed as { shortcuts?: unknown }).shortcuts !== null
          ? (parsed as { shortcuts: Record<string, unknown> }).shortcuts
          : parsed
      if (entries === null || typeof entries !== 'object' || Array.isArray(entries)) {
        flash('导入失败：文件格式不符合快捷键导出格式')
        return
      }
      const validIds = new Set(SHORTCUT_ACTIONS.map((a) => a.id))
      let applied = 0
      const unknown: string[] = []
      const reserved: string[] = []
      let current = customRef.current
      for (const [id, combo] of Object.entries(entries as Record<string, unknown>)) {
        if (!validIds.has(id) || typeof combo !== 'string') {
          unknown.push(id)
          continue
        }
        if (isReservedCombo(combo)) {
          reserved.push(id)
          continue
        }
        const { custom: next, error } = assignShortcut(current, id, combo, {
          overwrite: true,
        })
        if (error !== null) {
          reserved.push(id)
          continue
        }
        current = next
        applied += 1
      }
      applyCustom(current)
      const reasons: string[] = []
      if (unknown.length > 0) reasons.push(`未知动作 ${unknown.join('、')}`)
      if (reserved.length > 0) reasons.push(`保留组合 ${reserved.join('、')}`)
      flash(
        `导入完成：已应用 ${applied} 项，跳过 ${unknown.length + reserved.length} 项` +
          (reasons.length > 0 ? `（${reasons.join('；')}）` : ''),
      )
    },
    [applyCustom, flash],
  )

  const rows = effectiveShortcuts(custom)
  const hasOverrides = Object.keys(custom).length > 0

  return (
    <div className="py-2">
      <p className="mb-3 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
        列表上下文中的基础快捷键；输入框聚焦时不生效。点击「修改」后按下新组合键（Esc 取消 ·
        Backspace 清除）。用户自定义覆盖默认值（与「?」帮助弹窗同步），仅保存在当前设备。
      </p>

      {/* 操作区：全局恢复默认 + 导入/导出（44px 触控目标，可见焦点环由 Button 提供） */}
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <Button
          size="sm"
          className="min-h-11"
          disabled={!hasOverrides}
          onClick={() => {
            applyCustom({})
            flash('已全部恢复默认绑定')
          }}
        >
          恢复默认
        </Button>
        <Button size="sm" className="min-h-11" onClick={exportShortcuts}>
          <Download aria-hidden className="size-3.5" />
          导出
        </Button>
        <Button
          size="sm"
          className="min-h-11"
          onClick={() => fileInputRef.current?.click()}
        >
          <Upload aria-hidden className="size-3.5" />
          导入
        </Button>
        <input
          ref={fileInputRef}
          type="file"
          accept="application/json,.json"
          aria-label="导入快捷键 JSON 文件"
          className="sr-only"
          onChange={(event) => {
            const file = event.target.files?.[0]
            event.target.value = ''
            if (file !== undefined) void importShortcuts(file)
          }}
        />
      </div>

      {/* 状态区（导入汇总 / 保留组合拒绝 / 取消提示）：读屏可感知 */}
      {notice !== null && (
        <p role="status" className="mb-2 text-xs text-[var(--lumi-text-secondary)]">
          {notice}
        </p>
      )}

      {/* 冲突确认（显式覆盖，不静默抢占） */}
      {pending !== null && (
        <div
          role="alert"
          className="mb-2 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-3 text-xs leading-relaxed text-[var(--lumi-text-primary)]"
        >
          「{formatCombo(pending.combo)}」已被
          「{actionLabel(pending.conflictWith)}」使用。覆盖后
          「{actionLabel(pending.conflictWith)}」将回退到默认绑定。
          <div className="mt-2 flex gap-2">
            <Button size="sm" className="min-h-11" variant="primary" onClick={confirmOverwrite}>
              覆盖
            </Button>
            <Button size="sm" className="min-h-11" onClick={() => setPending(null)}>
              取消
            </Button>
          </div>
        </div>
      )}

      <dl className="divide-y divide-[var(--lumi-separator)]">
        {rows.map((row) => (
          <div
            key={row.id}
            className="flex items-center justify-between gap-4 py-2.5"
          >
            <dt className="flex min-w-0 items-center gap-2 text-sm text-[var(--lumi-text-primary)]">
              <span className="truncate">{row.action}</span>
              {row.overridden && (
                <span className="shrink-0 rounded-[var(--lumi-radius-full)] bg-[var(--lumi-surface-selected)] px-1.5 py-0.5 text-[10px] text-[var(--lumi-text-tertiary)]">
                  已自定义
                </span>
              )}
            </dt>
            <dd className="flex shrink-0 items-center gap-2">
              <kbd
                data-testid={`shortcut-keys-${row.id}`}
                className="rounded-[var(--lumi-radius-sm)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-0.5 font-mono text-xs text-[var(--lumi-text-secondary)]"
              >
                {row.keys}
              </kbd>
              {capturing === row.id ? (
                <Button
                  size="sm"
                  className="min-h-11"
                  variant="primary"
                  aria-label={`正在捕获新组合，点击取消：${row.action}`}
                  onClick={() => setCapturing(null)}
                >
                  按新组合键…
                </Button>
              ) : (
                <Button
                  size="sm"
                  className="min-h-11"
                  aria-label={`修改快捷键：${row.action}`}
                  onClick={() => {
                    setPending(null)
                    setCapturing(row.id)
                  }}
                >
                  修改
                </Button>
              )}
              <Button
                size="sm"
                className="min-h-11"
                disabled={!row.overridden}
                aria-label={`清除自定义，恢复默认：${row.action}`}
                onClick={() => {
                  applyCustom(resetShortcut(customRef.current, row.id))
                  flash('已清除自定义，恢复默认绑定')
                }}
              >
                清除
              </Button>
            </dd>
          </div>
        ))}
      </dl>
    </div>
  )
}

export default ShortcutsSettingsSection
