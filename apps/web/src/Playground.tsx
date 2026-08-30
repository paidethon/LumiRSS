/** UI Playground — 0009 Gate 1（AC17：仅 dev 可达）。
 *
 * dev-only 视觉验证路由：primitives × 主题 × 状态矩阵。生产构建不
 * 暴露任何入口（App 不引用本组件；仅 Vite dev 下手动访问 /playground
 * 对应的 hash 路由，见 main.tsx 的条件挂载）。 */

import { useState } from 'react'
import { Inbox, Loader2, Settings, Star, Trash2 } from 'lucide-react'
import { Button } from './components/ui/Button'
import { Dialog } from './components/ui/Dialog'
import { EmptyState } from './components/ui/EmptyState'
import { IconButton } from './components/ui/IconButton'
import { Menu } from './components/ui/Menu'
import { Popover } from './components/ui/Popover'
import { Select } from './components/ui/Select'
import { Sheet } from './components/ui/Sheet'
import { Skeleton } from './components/ui/Skeleton'
import { Switch } from './components/ui/Switch'
import { Tooltip } from './components/ui/Tooltip'
import { useTheme } from './store/theme'
import type { ThemeMode } from './lib/theme'
// 0012 Gate 11：Reader fixture（视觉/响应式/安全验证）
import { READER_FIXTURES } from './lib/playground-reader-fixtures'
import ArticleContent from './components/ArticleContent'
import { useAppSettings } from './store/app-settings'
import type {
  ReaderChineseConversion,
  ReaderTextIndent,
} from './store/app-settings'

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-[var(--lumi-radius-xl)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-4">
      <h2 className="mb-3 text-xs font-semibold uppercase tracking-wide text-[var(--lumi-text-tertiary)]">
        {title}
      </h2>
      <div className="flex flex-wrap items-center gap-3">{children}</div>
    </section>
  )
}

export default function Playground() {
  const mode = useTheme((s) => s.mode)
  const setMode = useTheme((s) => s.setMode)
  const [switchOn, setSwitchOn] = useState(true)
  const [dialogOpen, setDialogOpen] = useState(false)
  const [sheetOpen, setSheetOpen] = useState(false)
  const [select, setSelect] = useState('system')
  const [menuPick, setMenuPick] = useState('(未选择)')

  return (
    <div className="min-h-dvh bg-[var(--lumi-canvas)] p-6">
      <header className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-[var(--lumi-text-primary)]">
            Lumi UI Playground
          </h1>
          <p className="text-xs text-[var(--lumi-text-secondary)]">
            dev-only · primitives × 主题 × 状态（AC17：不进生产导航）
          </p>
        </div>
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
      </header>

      <div className="grid gap-4 lg:grid-cols-2">
        <Section title="Button">
          <Button variant="primary">主要操作</Button>
          <Button variant="secondary">次操作</Button>
          <Button variant="ghost">弱操作</Button>
          <Button variant="danger" onClick={() => setDialogOpen(true)}>
            <Trash2 aria-hidden /> 删除
          </Button>
          <Button disabled>禁用</Button>
          <Button size="sm">小尺寸</Button>
        </Section>

        <Section title="IconButton + Tooltip">
          <Tooltip content="收藏">
            <IconButton icon={<Star aria-hidden />} label="收藏" />
          </Tooltip>
          <Tooltip content="设置">
            <IconButton icon={<Settings aria-hidden />} label="设置" />
          </Tooltip>
          <IconButton icon={<Loader2 aria-hidden className="animate-spin" />} label="加载中" disabled />
          <IconButton icon={<Star aria-hidden />} label="收藏（触摸 44px）" touch />
        </Section>

        <Section title="Switch / Select">
          <Switch checked={switchOn} onCheckedChange={setSwitchOn} label="深色模式" />
          <Select
            aria-label="演示下拉"
            value={select}
            onChange={(e) => setSelect(e.target.value)}
            options={[
              { value: 'a', label: '选项 A' },
              { value: 'b', label: '选项 B' },
            ]}
          />
          <span className="text-xs text-[var(--lumi-text-secondary)]">
            当前值：{select}
          </span>
        </Section>

        <Section title="Menu / Popover">
          <Menu
            trigger={({ triggerProps }) => (
              <Button {...triggerProps}>菜单（选中：{menuPick}）</Button>
            )}
            items={[
              { key: 'a', content: '选项 A' },
              { key: 'b', content: '选项 B' },
              { key: 'c', content: '禁用项', disabled: true },
            ]}
            onSelect={setMenuPick}
          />
          <Popover
            trigger={({ triggerProps }) => (
              <Button {...triggerProps}>浮层</Button>
            )}
          >
            {(close) => (
              <div className="space-y-2">
                <p className="text-sm text-[var(--lumi-text-primary)]">浮层内容</p>
                <Button size="sm" onClick={close}>
                  关闭
                </Button>
              </div>
            )}
          </Popover>
          <Button onClick={() => setSheetOpen(true)}>打开 Sheet</Button>
        </Section>

        <Section title="Skeleton（加载态）">
          <div className="w-full space-y-2">
            <Skeleton className="h-7 w-3/4" />
            <Skeleton className="h-4 w-1/2" />
            <Skeleton className="h-4 w-5/6" />
          </div>
        </Section>

        <Section title="EmptyState（空态）">
          <EmptyState
            icon={<Inbox />}
            title="暂无文章"
            description="当前视图下没有内容，试试切换到全部或取消筛选。"
            action={
              <Button size="sm" variant="secondary">
                刷新
              </Button>
            }
          />
        </Section>

        <ReaderFixtureSection />
      </div>

      <Dialog
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
        title="确认删除"
        footer={
          <>
            <Button variant="ghost" onClick={() => setDialogOpen(false)}>
              取消
            </Button>
            <Button variant="danger" onClick={() => setDialogOpen(false)}>
              删除
            </Button>
          </>
        }
      >
        此操作不可撤销。
      </Dialog>

      <Sheet open={sheetOpen} onClose={() => setSheetOpen(false)} label="演示抽屉">
        <div className="p-4">
          <p className="text-sm text-[var(--lumi-text-primary)]">抽屉内容（Escape / 遮罩关闭）</p>
        </div>
      </Sheet>
    </div>
  )
}

/** 0012 Gate 11：Reader fixtures × transforms 开关矩阵（dev-only）。 */
function ReaderFixtureSection() {
  const [fixtureId, setFixtureId] = useState('chinese-long')
  const settings = useAppSettings((s) => s.settings)
  const update = useAppSettings((s) => s.update)
  const fixture = READER_FIXTURES.find((f) => f.id === fixtureId) ?? READER_FIXTURES[0]

  return (
    <section className="min-w-0 rounded-[var(--lumi-radius-xl)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] p-4 lg:col-span-2">
      <h2 className="mb-3 text-xs font-semibold uppercase tracking-wide text-[var(--lumi-text-tertiary)]">
        Reader Fixtures（0012）
      </h2>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Select
          aria-label="fixture"
          value={fixtureId}
          onChange={(e) => setFixtureId(e.target.value)}
          options={READER_FIXTURES.map((f) => ({ value: f.id, label: f.label }))}
        />
        <Select
          aria-label="简繁"
          value={settings.readerChineseConversion}
          onChange={(e) =>
            update({ readerChineseConversion: e.target.value as ReaderChineseConversion })
          }
          options={[
            { value: 'off', label: '原文' },
            { value: 's2t', label: '简→繁' },
            { value: 't2s', label: '繁→简' },
            { value: 'tw', label: '繁（台）' },
            { value: 'hk', label: '繁（港）' },
          ]}
        />
        <Select
          aria-label="首行缩进"
          value={settings.readerTextIndent}
          onChange={(e) => update({ readerTextIndent: e.target.value as ReaderTextIndent })}
          options={[
            { value: 'off', label: '无缩进' },
            { value: '2em', label: '缩进 2em' },
          ]}
        />
        <Switch
          checked={settings.readerBionic}
          onCheckedChange={(v) => update({ readerBionic: v })}
          label="词首强调"
        />
        <Switch
          checked={settings.readerHangingPunctuation}
          onCheckedChange={(v) => update({ readerHangingPunctuation: v })}
          label="标点悬挂"
        />
        <Switch
          checked={settings.readerCodeHighlight === 'auto'}
          onCheckedChange={(v) => update({ readerCodeHighlight: v ? 'auto' : 'off' })}
          label="代码高亮"
        />
      </div>
      {/* .lumi-reader 作用域（custom CSS / reader 变量消费同正式 Reader） */}
      <div className="lumi-reader rounded-[var(--lumi-radius-lg)] bg-[var(--lumi-reader-bg,transparent)] p-6 max-lg:p-4">
        <h3 className="text-[1.7rem] font-bold leading-snug text-[var(--lumi-text-primary)] max-lg:text-2xl">
          {fixture.detail.title}
        </h3>
        <div className="pt-4">
          <ArticleContent detail={fixture.detail} />
        </div>
      </div>
    </section>
  )
}
