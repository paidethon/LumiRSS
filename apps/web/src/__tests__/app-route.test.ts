/** app-route — 顶层极简路由（/activate、/admin）判定与导航测试。 */

import { afterEach, describe, expect, it, vi } from 'vitest'
import { readActivateToken, readAppRoute, navigateAppRoute } from '../lib/app-route'

function setUrl(url: string): void {
  window.history.replaceState(null, '', url)
}

afterEach(() => {
  setUrl('/')
})

describe('readAppRoute', () => {
  it('默认路径 → app', () => {
    setUrl('/')
    expect(readAppRoute()).toBe('app')
  })

  it('pathname /activate → activate（大小写不敏感的前缀段）', () => {
    setUrl('/activate?token=inv_abc')
    expect(readAppRoute()).toBe('activate')
  })

  it('pathname /admin → admin', () => {
    setUrl('/admin')
    expect(readAppRoute()).toBe('admin')
  })

  it('hash 形式 #/admin（静态托管兜底）→ admin', () => {
    setUrl('/#/admin')
    expect(readAppRoute()).toBe('admin')
  })

  it('hash 优先于 pathname', () => {
    setUrl('/activate#/admin')
    expect(readAppRoute()).toBe('admin')
  })

  it('其它路径（如 /entry）→ app', () => {
    setUrl('/something-else')
    expect(readAppRoute()).toBe('app')
  })
})

describe('navigateAppRoute', () => {
  it('push 到 /admin 并派发路由变化事件', () => {
    setUrl('/')
    const listener = vi.fn()
    window.addEventListener('lumirss-route-change', listener)
    navigateAppRoute('admin')
    window.removeEventListener('lumirss-route-change', listener)
    expect(window.location.pathname).toBe('/admin')
    expect(readAppRoute()).toBe('admin')
    expect(listener).toHaveBeenCalledTimes(1)
  })

  it('replace=true 不留历史（activate 成功回应用）', () => {
    setUrl('/activate?token=inv_x')
    const pushSpy = vi.spyOn(window.history, 'pushState')
    navigateAppRoute('app', true)
    expect(pushSpy).not.toHaveBeenCalled()
    expect(window.location.pathname).toBe('/')
    pushSpy.mockRestore()
  })

  it('导航到 app 后旧 hash 被覆盖', () => {
    setUrl('/#/admin')
    navigateAppRoute('app', true)
    expect(window.location.hash).toBe('')
    expect(readAppRoute()).toBe('app')
  })
})

describe('readActivateToken', () => {
  it('从 ?token= 读取', () => {
    setUrl('/activate?token=inv_abc123')
    expect(readActivateToken()).toBe('inv_abc123')
  })

  it('hash 路由形式 #/activate?token=… 同样解析', () => {
    setUrl('/#/activate?token=inv_hash456')
    expect(readActivateToken()).toBe('inv_hash456')
  })

  it('无 token → null', () => {
    setUrl('/activate')
    expect(readActivateToken()).toBeNull()
  })
})
