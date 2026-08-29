import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { initTheme } from './lib/theme.ts'
import { watchSystemTheme } from './store/theme.ts'
import { initReaderBg } from './lib/reader-bg.ts'

// 0009 Gate 1：主题初始化（index.html 内联脚本已防首帧闪烁，这里在
// React 接管前对齐一次，并开始监听 system 模式下的系统偏好变化）。
initTheme()
watchSystemTheme()

// 0009 Gate 4：恢复持久化的 Reader 背景偏好（sepia/warm，挂
// data-reader 到 Reader 容器；follow 则不挂）。
initReaderBg()

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
