/** KeyboardReadingModePanel — NEW-352 外接键盘阅读模式（设置 → 快捷键）。
 *
 * 连接外接键盘时显示当前页面可执行命令，用户可暂时启用并测试：
 * - 检测：`(any-pointer: fine)` 粗判（无法判定如实说，不假装）；
 * - 启用：本会话临时（sessionStorage，关标签页失效，不写设置）；
 * - 命令目录：全局动作（含自定义重绑生效键位）+ 阅读页文章域键位；
 * - 探测区：启用后聚焦按下按键 → 只显示「会触发哪条命令」，绝不代为
 *   执行（训练期零误操作）；修饰键组合（Ctrl/⌘/Alt）与 IME 组合一律
 *   不匹配——系统快捷键不受影响（与既有全局处理器同一纪律）。 */

import { useMemo, useState, type KeyboardEvent } from 'react'
import { useReaderUi } from '../../store/reader-ui'
import { loadCustomShortcuts } from '../../lib/custom-shortcuts'
import {
  ACTION_LABELS,
  hasPhysicalKeyboard,
  kbReadingCommands,
  matchKeyboardProbe,
  readKbReadingSession,
  writeKbReadingSession,
} from '../../lib/keyboard-reading-mode'
import { Switch } from '../ui/Switch'

export function KeyboardReadingModePanel() {
  const selectedEntryRef = useReaderUi((s) => s.selectedEntryRef)
  const [keyboardState] = useState<boolean | null>(() => hasPhysicalKeyboard())
  const [sessionEnabled, setSessionEnabled] = useState(() => readKbReadingSession())
  const [probeResult, setProbeResult] = useState<string | null>(null)
  const custom = useMemo(() => loadCustomShortcuts(), [])
  const page = selectedEntryRef !== null ? 'reader' : 'list'
  const { probe, readerOnly } = useMemo(() => kbReadingCommands(custom, page), [custom, page])

  const toggleSession = (enabled: boolean) => {
    setSessionEnabled(enabled)
    writeKbReadingSession(enabled)
    setProbeResult(null)
  }

  const onProbeKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const id = matchKeyboardProbe(
      {
        key: event.key,
        ctrlKey: event.ctrlKey,
        metaKey: event.metaKey,
        altKey: event.altKey,
        isComposing: event.nativeEvent.isComposing,
        keyCode: event.keyCode,
      },
      custom,
    )
    // 探测绝不代为执行：不调用任何动作，也不阻止默认行为。
    setProbeResult(
      id === null
        ? `「${event.key || '未知键'}」不匹配任何命令（系统/浏览器自行处理）`
        : `会触发：${ACTION_LABELS[id] ?? id}`,
    )
  }

  const keyboardLabel =
    keyboardState === true
      ? '已检测到物理键盘（指针精度粗判）'
      : keyboardState === false
        ? '未检测到物理键盘（触屏设备？连接后可用）'
        : '无法判定键盘状态（此环境不支持检测）'

  return (
    <section aria-label="外接键盘阅读模式" data-n352-panel="" className="flex flex-col gap-3 py-1">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="text-sm font-medium leading-tight text-[var(--lumi-text-primary)]">
            外接键盘阅读模式
          </p>
          <p className="mt-1 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
            {keyboardLabel}。启用为<strong>本会话临时</strong>（关闭标签页即失效），
            仅显示与测试命令，不覆盖系统快捷键。
          </p>
        </div>
        <Switch
          label="本会话启用外接键盘阅读模式"
          checked={sessionEnabled}
          onCheckedChange={toggleSession}
        />
      </div>

      {/* 当前页面可执行命令 */}
      <div className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-2.5">
        <h3 className="text-xs font-medium text-[var(--lumi-text-tertiary)]" data-n352-page-label="">
          当前页面（{page === 'reader' ? '阅读页' : '列表页'}）可执行命令
        </h3>
        <ul data-testid="n352-command-list" className="mt-1.5 flex flex-col gap-1">
          {probe.map((command) => (
            <li
              key={command.id}
              data-n352-command={command.id}
              className="flex items-baseline gap-2 text-xs text-[var(--lumi-text-primary)]"
            >
              <kbd className="shrink-0 rounded-[var(--lumi-radius-sm)] border border-[var(--lumi-border)] px-1.5 py-0.5 font-mono text-[0.6875rem] leading-4 text-[var(--lumi-text-secondary)]">
                {command.keys}
              </kbd>
              <span className="min-w-0">
                {command.action}
                {command.overridden && (
                  <span className="ml-1 text-[var(--lumi-text-tertiary)]">（自定义）</span>
                )}
              </span>
            </li>
          ))}
        </ul>
        {readerOnly.length > 0 && (
          <>
            <h3 className="mt-2 text-xs font-medium text-[var(--lumi-text-tertiary)]">
              阅读页文章域键位（固定；受设置「纯键盘阅读定位」开关控制）
            </h3>
            <ul className="mt-1.5 flex flex-col gap-1">
              {readerOnly.map((command) => (
                <li key={command.id} className="flex items-baseline gap-2 text-xs text-[var(--lumi-text-primary)]">
                  <kbd className="shrink-0 rounded-[var(--lumi-radius-sm)] border border-[var(--lumi-border)] px-1.5 py-0.5 font-mono text-[0.6875rem] leading-4 text-[var(--lumi-text-secondary)]">
                    {command.keys}
                  </kbd>
                  <span>{command.action}</span>
                </li>
              ))}
            </ul>
          </>
        )}
      </div>

      {/* 探测区：只显示匹配结果，绝不执行 */}
      {sessionEnabled ? (
        <div className="flex flex-col gap-1.5">
          <div
            data-testid="n352-probe"
            role="group"
            aria-label="按键测试区"
            tabIndex={0}
            onKeyDown={onProbeKeyDown}
            className="min-h-16 rounded-[var(--lumi-radius-md)] border border-dashed border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-3 py-2.5 text-xs text-[var(--lumi-text-secondary)] outline-none focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
          >
            {probeResult === null ? (
              <span>聚焦此处按任意键测试——只显示会触发的命令，不会真的执行。</span>
            ) : (
              <span data-n352-probe-result="" aria-live="polite" className="text-[var(--lumi-text-primary)]">
                {probeResult}
              </span>
            )}
          </div>
          <p className="text-xs leading-relaxed text-[var(--lumi-text-tertiary)]">
            Ctrl / ⌘ / Alt 组合与输入法组合中的按键永远不匹配——系统快捷键
            （复制、切换应用等）不受本模式影响。
          </p>
        </div>
      ) : (
        <p className="text-xs leading-relaxed text-[var(--lumi-text-tertiary)]" data-n352-disabled-note="">
          启用后出现按键测试区（只读探测，不执行任何命令）。
        </p>
      )}
    </section>
  )
}

export default KeyboardReadingModePanel
