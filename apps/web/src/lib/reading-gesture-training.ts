/** reading-gesture-training — NEW-351 阅读手势训练页（手势目录）。
 *
 * 手势是肌肉记忆，练错会真的标已读/返回。训练页提供合成文章演练 +
 * 「启用哪些手势」的显式选择。本模块只放可测试的纯数据/纯函数：
 *
 * - 手势目录：id / 名称 / 位置 / 说明（训练页与测试同源）。启用状态
 *   **不在这里存储**——边缘返回沿用既有便携设置 `swipeBackGesture`
 *   （App.tsx 的 EdgeSwipeBack 挂载条件；单一事实源，绝不复制第二份），
 *   卡片滑动沿用既有 `cardSwipeAction`（'none' 即关闭）；
 * - 演练判定复用 lib/edge-swipe 的纯函数（swipeStartCandidate /
 *   swipeIntentMet / swipeShouldCommit / previewOffset）——练习的就是
 *   真实手势的同一套阈值，绝不另造一套。
 *
 * 演练只在训练页内的合成文章上进行；绝不改动真实内容的默认行为。 */

export interface ReadingGestureDef {
  id: 'edge-swipe-back' | 'card-swipe-action'
  label: string
  where: string
  description: string
  /** 启用状态落在哪个既有设置键（训练页读写同一键，无独立存储）。 */
  settingKey: 'swipeBackGesture' | 'cardSwipeAction'
}

export const READING_GESTURES: readonly ReadingGestureDef[] = [
  {
    id: 'edge-swipe-back',
    label: '左缘侧滑返回',
    where: '移动端视口 · 任意页面左缘 ≤20px',
    description: '从屏幕左缘向右滑，返回上一处（跟手预览；与浏览器原生边缘返回互让）。',
    settingKey: 'swipeBackGesture',
  },
  {
    id: 'card-swipe-action',
    label: '卡片滑动动作',
    where: '文章列表卡片（横向滑动 ≥80px）',
    description: '滑卡触发选定动作；选「无」即关闭（动作只对启用的卡片生效）。',
    settingKey: 'cardSwipeAction',
  },
] as const
