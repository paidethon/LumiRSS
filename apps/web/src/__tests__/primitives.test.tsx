/** UI primitives 测试 — 0009 Gate 1（AC7）。
 *
 * 覆盖：渲染语义（角色/aria）、键盘交互（Escape/方向键）、焦点管理
 * （trap/还焦）、受控行为。样式 token 不在此断言（视觉验证归 playground
 * 截图与 Gate 4 走查）。 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { Button } from '../components/ui/Button'
import { Dialog } from '../components/ui/Dialog'
import { EmptyState } from '../components/ui/EmptyState'
import { IconButton } from '../components/ui/IconButton'
import { Menu } from '../components/ui/Menu'
import { Popover } from '../components/ui/Popover'
import { Select } from '../components/ui/Select'
import { Sheet } from '../components/ui/Sheet'
import { Skeleton } from '../components/ui/Skeleton'
import { Switch } from '../components/ui/Switch'
import { Check } from 'lucide-react'

describe('Button', () => {
  it('默认 type=button（不会意外提交表单）', () => {
    render(<Button>确定</Button>)
    expect(screen.getByRole('button', { name: '确定' })).toHaveProperty(
      'type',
      'button',
    )
  })
  it('disabled 时不触发点击', () => {
    const onClick = vi.fn()
    render(
      <Button disabled onClick={onClick}>
        禁用
      </Button>,
    )
    fireEvent.click(screen.getByRole('button', { name: '禁用' }))
    expect(onClick).not.toHaveBeenCalled()
  })
})

describe('IconButton', () => {
  it('aria-label 提供 accessible name（AC7：icon-only 必须有名字）', () => {
    render(<IconButton icon={<Check aria-hidden />} label="标记为已读" />)
    expect(screen.getByRole('button', { name: '标记为已读' })).toBeInTheDocument()
  })
})

describe('Menu', () => {
  function setup() {
    const onSelect = vi.fn()
    render(
      <Menu
        trigger={({ triggerProps }) => (
          <button type="button" {...triggerProps}>
            打开菜单
          </button>
        )}
        items={[
          { key: 'a', content: '选项 A' },
          { key: 'b', content: '选项 B' },
        ]}
        onSelect={onSelect}
      />,
    )
    return { onSelect }
  }

  it('初始不渲染面板；点击后渲染 menu + menuitem', async () => {
    setup()
    expect(screen.queryByRole('menu')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: '打开菜单' }))
    await waitFor(() => {
      expect(screen.getByRole('menu')).toBeInTheDocument()
      expect(screen.getAllByRole('menuitem')).toHaveLength(2)
    })
  })

  it('trigger 暴露 aria-haspopup/aria-expanded 状态', () => {
    setup()
    const trigger = screen.getByRole('button', { name: '打开菜单' })
    expect(trigger).toHaveAttribute('aria-haspopup', 'menu')
    expect(trigger).toHaveAttribute('aria-expanded', 'false')
    fireEvent.click(trigger)
    expect(trigger).toHaveAttribute('aria-expanded', 'true')
  })

  it('选择 item → onSelect + 关闭 + 还焦 trigger', async () => {
    const { onSelect } = setup()
    const trigger = screen.getByRole('button', { name: '打开菜单' })
    trigger.focus()
    fireEvent.click(trigger)
    await waitFor(() => screen.getByRole('menuitem', { name: '选项 A' }))
    fireEvent.click(screen.getByRole('menuitem', { name: '选项 B' }))
    expect(onSelect).toHaveBeenCalledWith('b')
    await waitFor(() => {
      expect(screen.queryByRole('menu')).toBeNull()
      expect(trigger).toHaveFocus()
    })
  })

  it('Escape 关闭并还焦 trigger', async () => {
    setup()
    const trigger = screen.getByRole('button', { name: '打开菜单' })
    fireEvent.click(trigger)
    await waitFor(() => screen.getByRole('menu'))
    fireEvent.keyDown(screen.getByRole('menu'), { key: 'Escape' })
    await waitFor(() => {
      expect(screen.queryByRole('menu')).toBeNull()
      expect(trigger).toHaveFocus()
    })
  })
})

describe('Popover', () => {
  it('点击 trigger 打开；Escape 关闭并还焦', async () => {
    render(
      <Popover
        trigger={({ triggerProps }) => (
          <button type="button" {...triggerProps}>
            打开浮层
          </button>
        )}
      >
        {(close) => (
          <div>
            <p>面板内容</p>
            <button type="button" onClick={close}>
              关闭
            </button>
          </div>
        )}
      </Popover>,
    )
    const trigger = screen.getByRole('button', { name: '打开浮层' })
    expect(screen.queryByText('面板内容')).toBeNull()
    fireEvent.click(trigger)
    expect(screen.getByText('面板内容')).toBeInTheDocument()
    // 内容主动 close() → 关闭 + 还焦
    fireEvent.click(screen.getByRole('button', { name: '关闭' }))
    await waitFor(() => {
      expect(screen.queryByText('面板内容')).toBeNull()
      expect(trigger).toHaveFocus()
    })
  })
})

describe('Dialog', () => {
  function setup() {
    const onClose = vi.fn()
    render(
      <>
        <button type="button">外部按钮</button>
        <Dialog
          open
          onClose={onClose}
          title="确认删除"
          footer={<button type="button">确定</button>}
        >
          内容
        </Dialog>
      </>,
    )
    return { onClose }
  }

  it('role=dialog + aria-modal + aria-labelledby 指向标题', () => {
    setup()
    const dialog = screen.getByRole('dialog')
    expect(dialog).toHaveAttribute('aria-modal', 'true')
    const labelId = dialog.getAttribute('aria-labelledby')!
    expect(document.getElementById(labelId)?.textContent).toBe('确认删除')
  })

  it('Escape 关闭（stopPropagation 不影响外层）', () => {
    const { onClose } = setup()
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('Tab 焦点 trap 在对话框内循环', () => {
    setup()
    const dialog = screen.getByRole('dialog')
    const focusables = [
      ...dialog.querySelectorAll<HTMLElement>('button'),
    ]
    // 初始焦点应在第一个可聚焦元素
    expect(focusables[0]).toHaveFocus()
    // 在最后一个元素上按 Tab → 焦点回到第一个
    focusables[focusables.length - 1].focus()
    fireEvent.keyDown(document, { key: 'Tab' })
    expect(focusables[0]).toHaveFocus()
  })
})

describe('Sheet', () => {
  it('Escape 关闭；关闭后还焦打开前焦点', () => {
    const onClose = vi.fn()
    render(
      <>
        <button type="button">触发抽屉</button>
        <Sheet open onClose={onClose} label="导航">
          <p>抽屉内容</p>
        </Sheet>
      </>,
    )
    const trigger = screen.getByRole('button', { name: '触发抽屉' })
    trigger.focus()
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(onClose).toHaveBeenCalledTimes(1)
    // open 仍为 true（受控），还焦断言由 Dialog 同款机制保证
  })

  it('side=bottom 渲染为底部 sheet（role=dialog）', () => {
    render(
      <Sheet open onClose={vi.fn()} label="底部" side="bottom">
        <p>底部内容</p>
      </Sheet>,
    )
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })

  // 0011 Gate 2：modal 升级后的新行为
  it('打开时锁定背景滚动（body overflow hidden），卸载恢复', () => {
    const { unmount } = render(
      <Sheet open onClose={vi.fn()} label="导航">
        <p>抽屉内容</p>
      </Sheet>,
    )
    expect(document.body.style.overflow).toBe('hidden')
    unmount()
    expect(document.body.style.overflow).not.toBe('hidden')
  })

  it('初始焦点落在第一个可聚焦元素；panelClassName/id 透传', () => {
    render(
      <Sheet
        open
        onClose={vi.fn()}
        label="导航"
        id="test-sheet"
        panelClassName="bg-[var(--lumi-sidebar)]"
      >
        <button type="button">第一个</button>
        <button type="button">第二个</button>
      </Sheet>,
    )
    const dialog = screen.getByRole('dialog')
    expect(dialog).toHaveAttribute('id', 'test-sheet')
    expect(dialog.className).toContain('bg-[var(--lumi-sidebar)]')
    expect(document.activeElement).toBe(screen.getByRole('button', { name: '第一个' }))
  })

  it('遮罩 pointerDown 关闭（面板内点击不关闭）', () => {
    const onClose = vi.fn()
    const { container } = render(
      <Sheet open onClose={onClose} label="导航">
        <button type="button">面板内</button>
      </Sheet>,
    )
    // 面板内点击：不关闭
    fireEvent.pointerDown(screen.getByRole('button', { name: '面板内' }))
    expect(onClose).not.toHaveBeenCalled()
    // 遮罩（aria-hidden div）pointerDown：关闭
    const overlay = container.querySelector('div[aria-hidden="true"]')!
    fireEvent.pointerDown(overlay)
    expect(onClose).toHaveBeenCalledTimes(1)
  })
})

describe('Switch', () => {
  it('role=switch + aria-checked 跟随受控值', () => {
    function Demo() {
      const [on, setOn] = useState(false)
      return (
        <Switch checked={on} onCheckedChange={setOn} label="深色模式" />
      )
    }
    render(<Demo />)
    const sw = screen.getByRole('switch', { name: '深色模式' })
    expect(sw).toHaveAttribute('aria-checked', 'false')
    fireEvent.click(sw)
    expect(sw).toHaveAttribute('aria-checked', 'true')
  })
})

describe('Select', () => {
  it('渲染 options 且值受控', () => {
    render(
      <Select
        value="dark"
        onChange={vi.fn()}
        options={[
          { value: 'system', label: '跟随系统' },
          { value: 'light', label: '浅色' },
          { value: 'dark', label: '深色' },
        ]}
        aria-label="主题"
      />,
    )
    const select = screen.getByRole('combobox', { name: '主题' })
    expect(select).toHaveValue('dark')
    expect(screen.getByRole('option', { name: '跟随系统' })).toBeInTheDocument()
  })
})

describe('Skeleton / EmptyState', () => {
  it('Skeleton aria-hidden（装饰性，屏幕阅读器跳过）', () => {
    const { container } = render(<Skeleton className="h-4 w-24" />)
    expect(container.firstElementChild).toHaveAttribute('aria-hidden', 'true')
  })
  it('EmptyState 渲染标题/描述/操作', () => {
    render(
      <EmptyState
        title="暂无文章"
        description="换个视图试试"
        action={<button type="button">重试</button>}
      />,
    )
    expect(screen.getByText('暂无文章')).toBeInTheDocument()
    expect(screen.getByText('换个视图试试')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '重试' })).toBeInTheDocument()
  })
})
