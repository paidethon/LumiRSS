/** app-route — 顶层极简路由（/activate、/register、/admin）判定与导航测试。 */

import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  isSafeAuthRedirectPath,
  navigateAppRoute,
  navigateToPath,
  readActivateToken,
  readAppRoute,
  readAuthRedirectTarget,
} from '../lib/app-route'

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

describe('register 路由（P0-02 公开注册）', () => {
  it('pathname /register → register', () => {
    setUrl('/register')
    expect(readAppRoute()).toBe('register')
  })

  it('navigateAppRoute("register") → /register', () => {
    setUrl('/')
    navigateAppRoute('register')
    expect(window.location.pathname).toBe('/register')
    expect(readAppRoute()).toBe('register')
  })
})

describe('isSafeAuthRedirectPath（F015 开放重定向防护）', () => {
  it('合法：单 / 开头的同源路径', () => {
    expect(isSafeAuthRedirectPath('/library')).toBe(true)
    expect(isSafeAuthRedirectPath('/admin')).toBe(true)
    expect(isSafeAuthRedirectPath('/a/b?x=1')).toBe(true)
  })

  it('非法：空、相对、协议相对 //、反斜杠、scheme、控制字符', () => {
    expect(isSafeAuthRedirectPath(null)).toBe(false)
    expect(isSafeAuthRedirectPath('')).toBe(false)
    expect(isSafeAuthRedirectPath('library')).toBe(false)
    expect(isSafeAuthRedirectPath('//evil.com')).toBe(false)
    expect(isSafeAuthRedirectPath('/\\evil.com')).toBe(false)
    expect(isSafeAuthRedirectPath('https://evil.com')).toBe(false)
    expect(isSafeAuthRedirectPath('javascript:alert(1)')).toBe(false)
    expect(isSafeAuthRedirectPath('/a\nb')).toBe(false)
  })
})

describe('readAuthRedirectTarget（?next= 读取 + 归一）', () => {
  it('合法 ?next= 原样返回', () => {
    setUrl('/?next=%2Flibrary')
    expect(readAuthRedirectTarget()).toBe('/library')
  })

  it('非法 ?next=（//、scheme、空）→ null（回退默认页）', () => {
    setUrl('/?next=%2F%2Fevil.com')
    expect(readAuthRedirectTarget()).toBeNull()
    setUrl('/?next=https%3A%2F%2Fevil.example')
    expect(readAuthRedirectTarget()).toBeNull()
    setUrl('/?next=')
    expect(readAuthRedirectTarget()).toBeNull()
  })

  it('无 ?next= → null', () => {
    setUrl('/')
    expect(readAuthRedirectTarget()).toBeNull()
  })

  it('hash 路由形式 #/?next=… 同样解析', () => {
    setUrl('/#/?next=%2Flibrary')
    expect(readAuthRedirectTarget()).toBe('/library')
  })
})

describe('navigateToPath（认证后回任意同源路径）', () => {
  it('replace=true 时替换当前历史并派发路由事件', () => {
    setUrl('/?next=%2Flibrary')
    const listener = vi.fn()
    window.addEventListener('lumirss-route-change', listener)
    navigateToPath('/library', true)
    window.removeEventListener('lumirss-route-change', listener)
    expect(window.location.pathname).toBe('/library')
    expect(readAppRoute()).toBe('app')
    expect(listener).toHaveBeenCalledTimes(1)
  })
})
