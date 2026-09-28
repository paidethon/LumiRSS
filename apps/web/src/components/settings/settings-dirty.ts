/** settings-dirty — 设置表单脏状态的统一登记处（FIX-057）。
 *
 * 背景：设置中心里多个分区有「本地表单 + 显式保存按钮」（邮件 SMTP/
 * IMAP、存储保留、RSSHub 凭据、翻译、GPT 摘要、AI 配置档案……），
 * 各自独立计算 dirty；此前从分区离开（切分类 / 关设置）没有任何
 * 保护，未保存内容静默丢失，且各分区对「什么算脏」判断不一。
 *
 * 契约：
 * - 表单分区用 `useSettingsDirtySection(id, dirty)` 一行登记自己的
 *   脏状态；分区卸载（切分类 / 关闭设置）自动撤销登记；
 * - SettingsModal / MobileSettingsScreen 读 `useHasDirtySettings()`，
 *   在分类切换与壳关闭前统一弹「未保存更改」确认（放弃 / 继续），
 *   判定口径全设置中心一致；
 * - 登记是纯 UI 守护，不阻塞任何实际的保存动作。
 */

import { useEffect } from 'react'
import { create } from 'zustand'

interface SettingsDirtyState {
  /** 有未保存表单状态的分区 id 集合。 */
  dirtySections: ReadonlySet<string>
  setSectionDirty: (id: string, dirty: boolean) => void
  clearAll: () => void
}

export const useSettingsDirty = create<SettingsDirtyState>((set) => ({
  dirtySections: new Set<string>(),
  setSectionDirty: (id, dirty) =>
    set((state) => {
      if (state.dirtySections.has(id) === dirty) return state
      const next = new Set(state.dirtySections)
      if (dirty) next.add(id)
      else next.delete(id)
      return { dirtySections: next }
    }),
  clearAll: () => set({ dirtySections: new Set() }),
}))

/** 设置中心当前是否有任何分区存在未保存更改。 */
export function useHasDirtySettings(): boolean {
  return useSettingsDirty((s) => s.dirtySections.size > 0)
}

/** 表单分区登记：dirty 翻转即同步；卸载时撤销本分区登记。 */
export function useSettingsDirtySection(id: string, dirty: boolean): void {
  const setSectionDirty = useSettingsDirty((s) => s.setSectionDirty)
  useEffect(() => {
    setSectionDirty(id, dirty)
    return () => setSectionDirty(id, false)
  }, [id, dirty, setSectionDirty])
}
