import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { initTheme } from './lib/theme.ts'
import { watchSystemTheme } from './store/theme.ts'
import { initAppSettings, useAppSettings } from './store/app-settings.ts'
import { initSettingsSync } from './store/settings-sync.ts'
import { useReaderUi } from './store/reader-ui.ts'
import { importUrlFont, restoreLocalFonts } from './lib/reader-fonts.ts'

// 0009 Gate 1：主题初始化（index.html 内联脚本已防首帧闪烁，这里在
// React 接管前对齐一次，并开始监听 system 模式下的系统偏好变化）。
initTheme()
watchSystemTheme()

// 0009 Gate 4：恢复持久化的 Reader 背景偏好（sepia/warm，挂
// data-reader 到 Reader 容器；follow 则不挂）。
initAppSettings()

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

// 0009 Gate 1：dev-only playground（AC17）。静态 import 会进入生产
// bundle，用条件动态 import 保证生产完全不包含它；路由用 hash 判断，
// 无需引入 router。
if (import.meta.env.DEV && location.hash === '#/playground') {
  const { default: Playground } = await import('./Playground.tsx')
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <Playground />
    </StrictMode>,
  )
} else {
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <App />
      </QueryClientProvider>
    </StrictMode>,
  )
}
