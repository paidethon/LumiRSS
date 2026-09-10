import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode, useEffect } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import LoginScreen from './components/LoginScreen.tsx'
import { getAuthSession } from './api/client'
import { useAuthStore } from './store/auth.ts'
import { initAppSettings, useAppSettings, watchSystemTheme } from './store/app-settings.ts'
import { initSettingsSync } from './store/settings-sync.ts'
import { useReaderUi } from './store/reader-ui.ts'
import { importUrlFont, restoreLocalFonts } from './lib/reader-fonts.ts'

// 0020 AUDIT-008：主题单一真源 = 规范 app-settings（lumirss-settings）。
// index.html 内联脚本已防首帧闪烁；initAppSettings() 在 React 接管前
// 按当前设置对齐一次主题/排版/外观，watchSystemTheme() 仅在 system
// 模式下跟随 OS（显式 light/dark 不被覆盖）。旧 lumirss-theme 所有权已
// 从生产启动路径退役（仅 dev Playground 保留）。
initAppSettings()
watchSystemTheme()

// 0017：portable 设置 server 同步（local-first：hydration 与持久化
// 都是异步耐久层，不阻塞首屏与任何 UI 交互）。
initSettingsSync()

// 0010a Gate E（AC8）：启动时仅看未读——只影响启动默认，会话内
// 手动切换 view 不受影响。
if (useAppSettings.getState().settings.unreadOnly) {
  useReaderUi.setState({ view: 'unread' })
}

// 0012 Gate 2/3：恢复自定义字体——IndexedDB 本地字体全部重新注册；
// URL 字体按当前设置重新挂载（失败静默回退档位栈，正文不消失；
// 字体未注册完成前 CSS 自动 fallback，无 layout collapse）。异步执行，
// 不阻塞首屏。
void restoreLocalFonts().then(() => {
  const { readerFontUrl, readerFontUrlName } = useAppSettings.getState().settings
  if (readerFontUrl !== null) {
    void importUrlFont(readerFontUrl, readerFontUrlName || readerFontUrl).catch(() => {
      /* 网络字体失效：回退档位字体栈（AC：正文不消失） */
    })
  }
})

const queryClient = new QueryClient()

/** 会话认证门（Phase N）：启动时探测认证模式与登录态。
 *
 * - mode=basic（代理层 Basic Auth）→ 永远放行，Web 不建登录 UI；
 * - mode=session → 未登录渲染 LoginScreen，登录后挂 App；
 * - 探测失败（离线 / BFF 暂不可用）→ 放行：数据层会诚实展示网络
 *   错误，「连不上」绝不冒充「未登录」把用户送去登录页。
 * 登录态翻转后清空 query 缓存（登出/过期后不留旧文章数据）。 */
function AuthGate({ children }: { children: React.ReactNode }) {
  const status = useAuthStore((s) => s.status)
  const setStatus = useAuthStore((s) => s.setStatus)

  useEffect(() => {
    let cancelled = false
    getAuthSession()
      .then((probe) => {
        if (cancelled) return
        const auth = useAuthStore.getState()
        auth.setMode(probe.mode)
        setStatus(probe.mode === 'basic' || probe.authenticated ? 'authenticated' : 'unauthenticated')
      })
      .catch(() => {
        if (!cancelled) setStatus('authenticated')
      })
    return () => {
      cancelled = true
    }
  }, [setStatus])

  useEffect(() => {
    if (status === 'unauthenticated') {
      void queryClient.cancelQueries()
      queryClient.clear()
    }
  }, [status])

  if (status === 'checking') {
    return (
      <div className="flex min-h-dvh items-center justify-center bg-[var(--lumi-canvas)]">
        <img src="/icons/lumirss-icon.svg" alt="LumiRSS" className="size-14" decoding="async" />
      </div>
    )
  }
  if (status === 'unauthenticated') return <LoginScreen />
  return children
}

// 0009 Gate 1：dev-only playground（AC17）。静态 import 会进入生产
// bundle，用条件动态 import 保证生产完全不包含它；路由用 hash 判断，
// 无需引入 router。
if (import.meta.env.DEV && location.hash === '#/playground') {
  // dev-only 参考实验室：保留旧 store/theme.ts 的所有权（动态 import，
  // 不进入生产 bundle）。
  const [{ default: Playground }, { initTheme }, { watchSystemTheme: watchLegacyTheme }] =
    await Promise.all([
      import('./Playground.tsx'),
      import('./lib/theme.ts'),
      import('./store/theme.ts'),
    ])
  initTheme()
  watchLegacyTheme()
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <Playground />
    </StrictMode>,
  )
  } else {
    createRoot(document.getElementById('root')!).render(
      <StrictMode>
        <QueryClientProvider client={queryClient}>
          <AuthGate>
            <App />
          </AuthGate>
        </QueryClientProvider>
      </StrictMode>,
    )
  }
