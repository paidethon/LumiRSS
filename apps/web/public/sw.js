/* LumiRSS service worker — 极简 App Shell（Phase M）。
 *
 * 安全边界（不可放宽）：
 * - /api/* 一律直连网络：认证响应、私有文章数据、AI 输出永不进缓存；
 * - 只有内容寻址（build 哈希）的 /assets/* 允许 cache-first——它们不可变；
 * - 导航请求 network-first：在线永远拿最新 shell；离线时回退到最近
 *   一次成功缓存的 shell（此时 API 层会诚实显示「网络不可用」，
 *   绝不冒充会话过期/密码错误）。
 * - 无后台同步、无 push、无 precache 清单：安装零下载。
 * - 更新策略：字节差异触发 install；不 skipWaiting——旧标签页继续由
 *   旧 SW + 旧缓存服务（部署后旧哈希资源已从源站消失，旧页面的懒
 *   加载 chunk 只能来自旧缓存），新 SW 等所有旧客户端关闭后自然接管；
 *   activate 时清理旧版本缓存。
 */

const VERSION = 'v1'
const CACHE = `lumirss-shell-${VERSION}`

self.addEventListener('install', () => {
  // 无 precache：首次访问的资源由 fetch 事件运行时缓存。
  // 不 skipWaiting：旧标签页继续由旧 SW + 旧缓存服务（部署后旧哈希
  // 资源已从源站消失，旧页面的懒加载 chunk 只能来自旧缓存）；新 SW
  // 等所有旧客户端关闭后自然接管。
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    (async () => {
      const names = await caches.keys()
      await Promise.all(
        names.filter((name) => name !== CACHE).map((name) => caches.delete(name)),
      )
      await self.clients.claim()
    })(),
  )
})

self.addEventListener('fetch', (event) => {
  const request = event.request
  if (request.method !== 'GET') return
  const url = new URL(request.url)
  if (url.origin !== self.location.origin) return
  if (url.pathname.startsWith('/api/')) return

  if (url.pathname.startsWith('/assets/')) {
    // 内容寻址的不可变构建产物：cache-first。
    event.respondWith(
      (async () => {
        const cache = await caches.open(CACHE)
        const hit = await cache.match(request)
        if (hit) return hit
        const response = await fetch(request)
        if (response.ok) await cache.put(request, response.clone())
        return response
      })(),
    )
    return
  }

  if (request.mode === 'navigate') {
    // SPA shell：network-first，离线回退最近缓存副本。
    event.respondWith(
      (async () => {
        const cache = await caches.open(CACHE)
        try {
          const response = await fetch(request)
          if (response.ok) await cache.put('/', response.clone())
          return response
        } catch (error) {
          const shell = await cache.match('/')
          if (shell) return shell
          throw error
        }
      })(),
    )
  }
})
