/**
 * FIX-099 — 底栏（MobileTabBar）不得永久遮挡列表尾/保存按钮/弹窗动作。
 *
 * jsdom 不做布局，本文件以「来源级审计 + 结构断言」钉定契约：
 *   1. 所有 `<1024 底部净空类（max-lg:pb-[…]）` 必须含 --safe-bottom——
 *      底栏实际占位 = 48px 岛高 + 8px 下边距 + safe-area；固定像素
 *      （76px/84px）在全面屏（safe-bottom ≈ 34px）会差 6–14px，列表
 *      最后一条沉入底栏之下；
 *   2. EntryList 列表尾哨兵不得再用 inline paddingBottom 覆盖净空类
 *      （「已到底」态曾回落到 16px，最后一条文章被底栏遮住）；
 *   3. MobileTabBar 自身保留 safe-bottom 下边距（岛不贴屏幕底）；
 *   4. 弹窗动作行（Dialog footer）在面板内部、shrink-0——底栏 z 序在
 *      Dialog 之下（z-token 断言），不会被永久遮挡。
 */

import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative, resolve } from 'node:path'
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import MobileTabBar from '../components/MobileTabBar'

const srcRoot = resolve(__dirname, '..')

function walk(dir: string): string[] {
  const out: string[] = []
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    const st = statSync(p)
    if (st.isDirectory()) {
      if (name === '__tests__' || name === 'generated') continue
      out.push(...walk(p))
    } else if (/\.(tsx|ts|css)$/.test(name)) {
      out.push(p)
    }
  }
  return out
}

describe('FIX-099: 底栏净空与 safe-area 一致', () => {
  it('所有 max-lg:pb-[…] 底部净空类都计入 --safe-bottom', () => {
    const offenders: string[] = []
    for (const file of walk(srcRoot)) {
      const rel = relative(srcRoot, file)
      if (rel.startsWith('__tests__')) continue
      const text = readFileSync(file, 'utf-8')
      for (const m of text.matchAll(/max-lg:pb-\[([^\]"]+)\]/g)) {
        if (!m[1].includes('--safe-bottom')) {
          const line = text.slice(0, m.index).split('\n').length
          offenders.push(`${rel}:${line} max-lg:pb-[${m[1]}]`)
        }
      }
    }
    expect(offenders).toEqual([])
  })

  it('EntryList 列表尾哨兵不再用 inline paddingBottom 覆盖净空类', () => {
    const text = readFileSync(resolve(srcRoot, 'components/EntryList.tsx'), 'utf-8')
    expect(text).not.toContain('paddingBottom: hasNextPage')
    expect(text).toContain('max-lg:pb-[max(5.25rem,calc(3.5rem_+_0.5rem_+_var(--safe-bottom)))]')
  })

  it('MobileTabBar 结构：底栏自身预留 safe-bottom 下边距、隐藏于 ≥1024', () => {
    render(<MobileTabBar />)
    const nav = screen.getByRole('navigation', { name: '底部导航' })
    // 结构断言（jsdom 无布局）：净空表达式 + lg 隐藏
    expect(nav.getAttribute('style')).toContain('var(--safe-bottom)')
    expect(nav.className).toContain('lg:hidden')
  })

  it('Dialog 层级高于底栏（--lumi-z-dialog token），动作行不被永久遮挡', () => {
    const dialogSrc = readFileSync(resolve(srcRoot, 'components/ui/Dialog.tsx'), 'utf-8')
    expect(dialogSrc).toContain('z-[var(--lumi-z-dialog)]')
    // footer 在面板内部（shrink-0 随面板滚动体系，不在视口底固定层）
    expect(dialogSrc).toContain('footer && <div className="mt-5 flex shrink-0 justify-end gap-2">')
  })
})
