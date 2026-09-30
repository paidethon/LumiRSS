/** auth-gate — 会话认证门的行为本体（main.tsx AuthGate 与测试共用）。
 *
 * 职责（Phase N + 0067 + FIX-069）：
 * - 挂载时探测 /auth/session：mode=basic 放行；session 按登录态放行；
 *   探测失败（离线）放行——「连不上」绝不冒充「未登录」；
 * - probeNonce 递增（跨标签页身份同步、显式刷新入口）时重新探测；
 * - 翻到 unauthenticated 时取消在途查询并清空缓存（登出/过期后不留
 *   旧文章数据）；
 * - FIX-069：监听 auth epoch 的 storage 事件——另一标签页完成了登录/
 *   登出时，本标签页清空旧身份的缓存与足迹、回 checking 重新探测
 *   （共享 cookie 已是新身份）。只处理「本标签页仍挂着应用子树」的
 *   场景（status === 'authenticated'），且处理过程不再次广播（否则
 *   标签页间乒乓循环）。
 * - FIX-278：监听 pageshow persisted=true（浏览器 back-forward cache
 *   恢复快照——JS 状态原样复活，离开期间会话可能已被撤销/过期）。
 *   先回 checking 摘下应用子树（私有内容交互暂停），再走 probeNonce
 *   重探 /auth/session，按服务端结果放行；探测失败（离线）照旧放行
 *   ——「连不上」不冒充「未登录」。persisted=false 与非 authenticated
 *   状态不触发（普通加载/登录页无需复核）。
 */

import { useEffect } from 'react'
import type { QueryClient } from '@tanstack/react-query'
import { getAuthSession } from '../api/client'
import { AUTH_EPOCH_STORAGE_KEY, identityFromSession, useAuthStore, type AuthGateStatus } from '../store/auth'
import { resetAccountState } from './auth-reset'

export function useAuthGate(queryClient: QueryClient): AuthGateStatus {
  const status = useAuthStore((s) => s.status)
  const probeNonce = useAuthStore((s) => s.probeNonce)

  useEffect(() => {
    let cancelled = false
    getAuthSession()
      .then((probe) => {
        if (cancelled) return
        const auth = useAuthStore.getState()
        auth.setMode(probe.mode)
        // 0067：身份由服务端核实（未认证/缺字段 → null，账号菜单隐藏）
        auth.setIdentity(identityFromSession(probe))
        useAuthStore
          .getState()
          .setStatus(probe.mode === 'basic' || probe.authenticated ? 'authenticated' : 'unauthenticated')
      })
      .catch(() => {
        if (!cancelled) useAuthStore.getState().setStatus('authenticated')
      })
    return () => {
      cancelled = true
    }
  }, [probeNonce])

  useEffect(() => {
    if (status === 'unauthenticated') {
      void queryClient.cancelQueries()
      queryClient.clear()
    }
  }, [status, queryClient])

  useEffect(() => {
    function onPageShow(event: PageTransitionEvent): void {
      // 只处理 bfcache 恢复（persisted=true）；普通加载不重探。
      if (!event.persisted) return
      // 只复核还挂着应用子树的标签页；登录页/探测中无需复核。
      if (useAuthStore.getState().status !== 'authenticated') return
      // 先回 checking：AuthGate 摘下应用子树，私有内容交互暂停；
      // probeNonce 递增驱动重新探测，按服务端结果放行（见上方 effect）。
      useAuthStore.getState().setStatus('checking')
      useAuthStore.getState().requestProbe()
    }
    window.addEventListener('pageshow', onPageShow)
    return () => window.removeEventListener('pageshow', onPageShow)
  }, [])

  useEffect(() => {
    function onStorage(event: StorageEvent): void {
      if (event.key !== null && event.key !== AUTH_EPOCH_STORAGE_KEY) return
      // 只有还挂着应用子树的标签页需要重置；登录页/探测中的标签页
      // 没有旧身份状态可泄漏，忽略事件避免多余的探测循环。
      if (useAuthStore.getState().status !== 'authenticated') return
      // 旧身份的缓存与本机足迹全部作废（不再广播——事件源自其他
      // 标签页，再广播会让标签页间互相触发、乒乓循环）。
      resetAccountState(queryClient, { broadcast: false })
      const auth = useAuthStore.getState()
      auth.setIdentity(null)
      auth.setStatus('checking')
      auth.requestProbe()
    }
    window.addEventListener('storage', onStorage)
    return () => window.removeEventListener('storage', onStorage)
  }, [queryClient])

  return status
}
