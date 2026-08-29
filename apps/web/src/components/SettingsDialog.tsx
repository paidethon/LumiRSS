/** SettingsDialog — 设置壳（0009 Gate 4，AC18）。
 *
 * 仅视觉结构 + 真实可用的 Appearance 控件：
 * - 外观（真实工作）：主题模式三态（system/light/dark，写 localStorage
 *   + data-theme——与 playground 同一 store）+ Reader 背景（follow/sepia/
 *   warm，挂 data-reader 到 Reader 容器）；
 * - 通用 / 阅读 / 数据与备份 / 关于：占位分组，明确标注「planned」，
 *   不存在假装可保存的控件（AC19）。
 *
 * 完整设置（订阅/RSSHub/AI/备份）归 0010+/0014；本组件是壳与入口。 */

import { useEffect, useState } from 'react'
import { BookOpen, Bot, Database, Info, Palette } from 'lucide-react'
import { useTheme } from '../store/theme'
import type { ThemeMode } from '../lib/theme'
import {
  type ReaderBg,
  applyReaderBg,
  initReaderBg,
  readStoredReaderBg,
} from '../lib/reader-bg'
import { Dialog } from './ui/Dialog'
import { Select } from './ui/Select'

/** 占位分组：标题 + planned 徽标 + 说明（无假控件） */
function PlannedSection({
  icon,
  title,
  description,
}: {
  icon: React.ReactNode
  title: string
  description: string
}) {
  return (
    <section className="rounded-[var(--lumi-radius-xl)] border border-[var(--lumi-border)] p-3.5">
      <div className="flex items-center gap-2">
        <span className="text-[var(--lumi-text-tertiary)] [&_svg]:size-4">{icon}</span>
        <h3 className="text-sm font-medium text-[var(--lumi-text-primary)]">{title}</h3>
        <span className="ml-auto rounded-[var(--lumi-radius-full)] bg-[var(--lumi-surface-selected)] px-2 py-0.5 text-[11px] text-[var(--lumi-text-tertiary)]">
          planned
        </span>
      </div>
      <p className="mt-1.5 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
        {description}
      </p>
    </section>
  )
}

export default function SettingsDialog({
  open,
  onClose,
}: {
  open: boolean
  onClose: () => void
}) {
  const mode = useTheme((s) => s.mode)
  const setMode = useTheme((s) => s.setMode)
  // 受控值：打开时从 localStorage 读一次（避免 render 中直接读 storage
  // 触发 React Compiler 警告）；切换时同步写回 + 挂 data-reader。
  const [readerBg, setReaderBg] = useState<ReaderBg>('follow')

  useEffect(() => {
    if (open) {
      initReaderBg()
      setReaderBg(readStoredReaderBg())
    }
  }, [open])

  const onReaderBgChange = (bg: ReaderBg) => {
    applyReaderBg(bg)
    setReaderBg(bg)
  }

  return (
    <Dialog open={open} onClose={onClose} title="设置">
      <div className="flex flex-col gap-3">
        {/* 外观：真实可用（AC18） */}
        <section className="rounded-[var(--lumi-radius-xl)] border border-[var(--lumi-border)] p-3.5">
          <div className="flex items-center gap-2">
            <span className="text-[var(--lumi-text-tertiary)]">
              <Palette aria-hidden className="size-4" />
            </span>
            <h3 className="text-sm font-medium text-[var(--lumi-text-primary)]">外观</h3>
          </div>
          <div className="mt-3 flex flex-col gap-2.5">
            <label className="flex items-center justify-between gap-3 text-sm text-[var(--lumi-text-primary)]">
              主题模式
              <Select
                aria-label="主题模式"
                value={mode}
                onChange={(e) => setMode(e.target.value as ThemeMode)}
                options={[
                  { value: 'system', label: '跟随系统' },
                  { value: 'light', label: '浅色' },
                  { value: 'dark', label: '深色' },
                ]}
              />
            </label>
            <label className="flex items-center justify-between gap-3 text-sm text-[var(--lumi-text-primary)]">
              阅读背景
              <Select
                aria-label="阅读背景"
                value={readerBg}
                onChange={(e) => onReaderBgChange(e.target.value as ReaderBg)}
                options={[
                  { value: 'follow', label: '跟随主题' },
                  { value: 'sepia', label: '纸黄' },
                  { value: 'warm', label: '暖白' },
                ]}
              />
            </label>
          </div>
        </section>

        {/* 占位分组：明确 planned，无假控件 */}
        <PlannedSection
          icon={<BookOpen aria-hidden />}
          title="阅读"
          description="字体、字号、行距与正文宽度偏好（0014 统一设置实现）。"
        />
        <PlannedSection
          icon={<Database aria-hidden />}
          title="订阅与来源"
          description="订阅管理、OPML 与 RSSHub 路由（0010–0011）。"
        />
        <PlannedSection
          icon={<Bot aria-hidden />}
          title="AI"
          description="摘要与翻译的 Provider 配置（0012–0013）。"
        />
        <PlannedSection
          icon={<Info aria-hidden />}
          title="数据与备份"
          description="备份、恢复与诊断（0015）。"
        />
      </div>
    </Dialog>
  )
}
