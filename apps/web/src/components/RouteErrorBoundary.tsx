/** RouteErrorBoundary — FIX-259：路由级错误边界。
 *
 * 此前全 App（main.tsx → App → 各一级页）没有任何 ErrorBoundary：
 * 任何一级页在渲染期抛错（坏参数/异常 DTO/坏 chunk）都会让 React
 * 卸载整树 = 整个 App 白屏，只能手动刷新。
 *
 * 本边界只包裹一级页的路由位：错误面只替换该页区域（Sidebar 等壳层
 * 不受影响），并提供两条恢复路径——「重试」（就地复位边界重挂本页）
 * 与「返回首页」（回到有效的 home 时间线）。
 *
 * 语义约定：
 * - 顶层路由（/admin 由 App 的 route 分支承载）与 App 内 section 页共用；
 * - 不做自动上报（无后端端点）；错误文本仅含 message（无堆栈/无数据）。
 */

import { Component, type ReactNode } from 'react'
import { RotateCcw } from 'lucide-react'
import { useReaderUi } from '../store/reader-ui'

type Props = {
  /** 错误面标题里的页面名（如「收藏」「搜索」） */
  label: string
  children: ReactNode
}

type State = { error: Error | null }

export class RouteErrorBoundary extends Component<Props, State> {
  override state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  override componentDidCatch(error: Error): void {
    // 控制台留痕便于开发期定位；不向浏览器外发任何数据。
    console.error(`[RouteErrorBoundary] ${this.props.label}页面渲染失败:`, error.message)
  }

  private readonly handleBackHome = (): void => {
    // 先复位边界再切路由：section 变化会卸载本边界（条件挂载），
    // setState 保证同 section 边界复用路径下也已复位。
    this.setState({ error: null })
    useReaderUi.getState().selectSection('home')
  }

  private readonly handleRetry = (): void => {
    this.setState({ error: null })
  }

  override render(): ReactNode {
    const { error } = this.state
    if (error === null) {
      return this.props.children
    }
    return (
      <div
        role="alert"
        data-testid="route-error-surface"
        className="flex min-h-0 flex-1 flex-col items-center justify-center gap-3 overflow-y-auto p-6 text-center"
      >
        <p className="text-sm font-medium text-[var(--lumi-text-primary)]">
          {this.props.label}页面出错，其余功能不受影响。
        </p>
        <p className="max-w-md text-xs leading-relaxed text-[var(--lumi-text-tertiary)]">
          {error.message}
        </p>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={this.handleRetry}
            className="flex min-h-11 items-center justify-center gap-1.5 rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] px-3 text-sm text-[var(--lumi-text-primary)] transition-colors duration-[var(--lumi-motion-fast)] hover:bg-[var(--lumi-surface-hover)] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
          >
            <RotateCcw aria-hidden className="size-4" />
            重试
          </button>
          <button
            type="button"
            onClick={this.handleBackHome}
            className="flex min-h-11 items-center justify-center rounded-[var(--lumi-radius-md)] bg-[var(--lumi-accent)] px-3 text-sm text-[var(--lumi-accent-contrast)] transition-colors duration-[var(--lumi-motion-fast)] hover:opacity-90 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]"
          >
            返回首页
          </button>
        </div>
      </div>
    )
  }
}
