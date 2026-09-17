/** 撤销（F20）——最近一次行内操作的可逆窗口。
 *
 * 单槽设计：只保留最近一条可撤销动作（新动作覆盖旧动作），8 秒后
 * 自动过期。撤销执行前的状态核对由 action.check 承担——服务器状态
 * 与我们设置的不一致（另一设备已改动）时拒绝执行并如实提示，
 * 绝不盲目翻转覆盖。 */

import { create } from 'zustand'

export interface UndoAction {
  /** 展示文案（如「已标记已读」） */
  label: string
  /** 逆操作（set 语义 PATCH，幂等） */
  undo: () => Promise<void>
  /** 执行逆操作前的状态核对；false = 状态已变，拒绝撤销 */
  check: () => Promise<boolean>
}

interface UndoState {
  current: (UndoAction & { expiresAt: number }) | null
  push: (action: UndoAction, ttlMs?: number) => void
  clear: () => void
  /** 过期清理（由组件的定时器驱动，避免常驻轮询） */
  expire: () => void
}

export const useUndo = create<UndoState>((set) => ({
  current: null,
  push: (action, ttlMs = 8000) =>
    set({ current: { ...action, expiresAt: Date.now() + ttlMs } }),
  clear: () => set({ current: null }),
  expire: () =>
    set((state) =>
      state.current && state.current.expiresAt <= Date.now()
        ? { current: null }
        : state,
    ),
}))
