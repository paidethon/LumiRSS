/** ReaderToolbarCustomizeDialog — P07 阅读器工具栏自定义对话框。
 *
 * 从「更多操作 → 自定义工具栏」进入。只组合 components/ui 原语
 * （Dialog + Tabs + Button + IconButton + Switch；Base UI 的 Escape
 * 关闭 / 焦点陷阱 / 滚动锁全部由 Dialog 原语承载，此处零自研浮层行为）。
 *
 * 交互（Spec P07）：
 * - 桌面 / 移动端两个 Tab 各自编辑（设备本地两套键，见 store/app-settings.ts）；
 * - 每行一个注册表动作：上移/下移（IconButton touch = 44×44 触达、
 *   键盘可达、焦点环 token）调序；Switch 控制显示/隐藏；
 * - 锁定动作（收藏 / 更多操作）开关禁用 + 「不可移除」标记——结构上
 *   保证至少一个动作可见；
 * - 恢复默认 = 重置工作副本（仍需「保存」提交）；取消 = 丢弃改动；
 * - 保存 = 写回 store（store 侧再经 normalizeReaderToolbarOrder 归一化：
 *   去重 / 丢未知 / 补缺项，隐藏以 '-id' 占位持久化）。 */

import { useState } from 'react'
import { ArrowDown, ArrowUp } from 'lucide-react'
import { useAppSettings } from '../store/app-settings'
import {
  defaultReaderToolbarOrder,
  parseReaderToolbarEntry,
  readerToolbarAction,
  type ReaderToolbarActionId,
  type ReaderToolbarScope,
} from '../lib/reader-toolbar'
import { Button } from './ui/Button'
import { Dialog } from './ui/Dialog'
import { IconButton } from './ui/IconButton'
import { Switch } from './ui/Switch'
import { Tabs } from './ui/Tabs'

/** 工作副本行：动作 id + 是否显示（顺序 = 列表顺序 = 工具栏顺序）。 */
interface ToolbarRow {
  id: ReaderToolbarActionId
  visible: boolean
}

/** 从（已归一化的）store 值铺开工作副本：可见段在前按序，隐藏段在后。 */
function rowsFromStored(stored: unknown, scope: ReaderToolbarScope): ToolbarRow[] {
  const source = Array.isArray(stored) ? stored : defaultReaderToolbarOrder(scope)
  const rows: ToolbarRow[] = []
  const seen = new Set<ReaderToolbarActionId>()
  for (const entry of source) {
    const parsed = parseReaderToolbarEntry(entry)
    if (parsed === null || seen.has(parsed.id)) continue
    seen.add(parsed.id)
    rows.push({ id: parsed.id, visible: parsed.visible })
  }
  // 缺项补全 / 锁定强制可见（store 值已归一化；此处纯防御，对齐 normalize）
  for (const id of defaultReaderToolbarOrder(scope)) {
    if (!seen.has(id)) rows.push({ id, visible: true })
  }
  return rows.map((row) =>
    readerToolbarAction(row.id).locked && !row.visible ? { ...row, visible: true } : row,
  )
}

/** 序列化为存储形式：可见 'id' 在前按序，隐藏 '-id' 占位在后。 */
function serializeRows(rows: ToolbarRow[]): string[] {
  return [
    ...rows.filter((row) => row.visible).map((row) => row.id),
    ...rows.filter((row) => !row.visible).map((row) => `-${row.id}`),
  ]
}

const SCOPE_LABELS: Record<ReaderToolbarScope, string> = { desktop: '桌面端', mobile: '移动端' }

export default function ReaderToolbarCustomizeDialog({
  open,
  onClose,
}: {
  open: boolean
  onClose: () => void
}) {
  const update = useAppSettings((s) => s.update)
  const [scope, setScope] = useState<ReaderToolbarScope>('desktop')
  // 工作副本在挂载时从 store 取值初始化（调用方仅在打开时挂载本组件，
  // 见 ReaderHeader；取消 / Escape / 保存后卸载，重开即重新初始化）。
  const [rowsByScope, setRowsByScope] = useState<Record<ReaderToolbarScope, ToolbarRow[]>>(
    () => ({
      desktop: rowsFromStored(useAppSettings.getState().settings.readerToolbarDesktopOrder, 'desktop'),
      mobile: rowsFromStored(useAppSettings.getState().settings.readerToolbarMobileOrder, 'mobile'),
    }),
  )

  const patchScope = (patch: Partial<Record<ReaderToolbarScope, ToolbarRow[]>>) => {
    setRowsByScope((current) => ({ ...current, ...patch }))
  }

  const moveRow = (scopeKey: ReaderToolbarScope, index: number, delta: -1 | 1) => {
    const list = [...rowsByScope[scopeKey]]
    const target = index + delta
    if (target < 0 || target >= list.length) return
    ;[list[index], list[target]] = [list[target], list[index]]
    patchScope({ [scopeKey]: list })
  }

  const setRowVisible = (scopeKey: ReaderToolbarScope, id: ReaderToolbarActionId, visible: boolean) => {
    patchScope({
      [scopeKey]: rowsByScope[scopeKey].map((row) => (row.id === id ? { ...row, visible } : row)),
    })
  }

  const resetToDefaults = () => {
    patchScope({
      desktop: defaultReaderToolbarOrder('desktop').map((id) => ({ id, visible: true })),
      mobile: defaultReaderToolbarOrder('mobile').map((id) => ({ id, visible: true })),
    })
  }

  const save = () => {
    update({
      readerToolbarDesktopOrder: serializeRows(rowsByScope.desktop),
      readerToolbarMobileOrder: serializeRows(rowsByScope.mobile),
    })
    onClose()
  }

  const renderList = (scopeKey: ReaderToolbarScope) => {
    const rows = rowsByScope[scopeKey]
    return (
      <div>
        <p className="mb-2 text-xs text-[var(--lumi-text-tertiary)]">
          用上移 / 下移调整顺序，开关控制显示 / 隐藏；{SCOPE_LABELS[scopeKey]}
          的排布只记在本设备。锁定动作不可移除。
        </p>
        <ul className="flex flex-col gap-1" aria-label={`${SCOPE_LABELS[scopeKey]}工具栏动作`}>
          {rows.map((row, index) => {
            const def = readerToolbarAction(row.id)
            const Icon = def.icon
            return (
              <li
                key={row.id}
                className="flex items-center gap-0.5 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-1 py-0.5"
              >
                <IconButton
                  icon={<ArrowUp aria-hidden className="size-4" />}
                  label={`上移${def.label}`}
                  size="sm"
                  touch
                  disabled={index === 0}
                  onClick={() => moveRow(scopeKey, index, -1)}
                />
                <IconButton
                  icon={<ArrowDown aria-hidden className="size-4" />}
                  label={`下移${def.label}`}
                  size="sm"
                  touch
                  disabled={index === rows.length - 1}
                  onClick={() => moveRow(scopeKey, index, 1)}
                />
                <span className="ml-1 flex min-w-0 flex-1 items-center gap-2 py-1">
                  <Icon aria-hidden className="size-4 shrink-0 text-[var(--lumi-text-secondary)]" />
                  <span className="truncate text-sm text-[var(--lumi-text-primary)]">{def.label}</span>
                  {scopeKey === 'mobile' && (
                    <span className="shrink-0 rounded-[var(--lumi-radius-sm)] bg-[var(--lumi-surface)] px-1.5 py-0.5 text-xs text-[var(--lumi-text-tertiary)]">
                      {def.primary ? '工具栏' : '菜单'}
                    </span>
                  )}
                  {def.locked && (
                    <span className="shrink-0 text-xs text-[var(--lumi-text-tertiary)]">不可移除</span>
                  )}
                </span>
                <Switch
                  checked={row.visible}
                  disabled={def.locked}
                  label={`显示${def.label}`}
                  onCheckedChange={(next) => setRowVisible(scopeKey, row.id, next)}
                />
              </li>
            )
          })}
        </ul>
      </div>
    )
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="自定义工具栏"
      panelClassName="max-w-lg"
      footer={
        <>
          <Button variant="ghost" className="mr-auto" onClick={resetToDefaults}>
            恢复默认
          </Button>
          <Button variant="ghost" onClick={onClose}>
            取消
          </Button>
          <Button variant="primary" onClick={save}>
            保存
          </Button>
        </>
      }
    >
      <Tabs<ReaderToolbarScope>
        aria-label="自定义工具栏断点"
        value={scope}
        onValueChange={setScope}
        options={[
          { value: 'desktop', label: SCOPE_LABELS.desktop },
          { value: 'mobile', label: SCOPE_LABELS.mobile },
        ]}
        panels={{ desktop: renderList('desktop'), mobile: renderList('mobile') }}
      />
    </Dialog>
  )
}
