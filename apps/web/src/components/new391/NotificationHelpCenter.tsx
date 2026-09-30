/** NotificationHelpCenter — NEW-391..400 通知、发布变化与帮助闭环
 * 组合面板（设置页挂载点）。
 *
 * 情境展开（折叠 = 不挂载子面板 = 零请求）；全部子面板的诚实边界由
 * 各自的 BFF 面负责（services/bff/src/lumirss/new391..400_*.py）。
 */

import { NotificationCenterPanel, AggregationRulesPanel } from './NotificationCenterPanel'
import { QuietHoursPanel } from './QuietHoursPanel'
import { ExperienceChecklistPanel } from './ExperienceChecklistPanel'
import { InteractionModePrefsPanel } from './InteractionModePrefsPanel'
import { ServiceStatusPanel } from './ServiceStatusPanel'
import { RunbookPanel } from './RunbookPanel'
import { DocFeedbackPanel } from './DocFeedbackPanel'
import { ModuleCleanupPanel } from './ModuleCleanupPanel'
import { SubSection } from './parts'

export function NotificationHelpCenter() {
  return (
    <div data-n391-center className="flex flex-col gap-2">
      <SubSection id="notification-inbox" label="通知收件箱（真实事件 · 按类型处理 · 撤销失效提示）">
        <NotificationCenterPanel />
      </SubSection>
      <SubSection id="notification-aggregation" label="通知聚合规则（同来源合并，可展开原始事件）">
        <AggregationRulesPanel />
      </SubSection>
      <SubSection id="notification-quiet" label="提醒静默时段（结束后汇总未读）">
        {(open) => (open ? <QuietHoursPanel /> : null)}
      </SubSection>
      <SubSection id="experience-checklist" label="版本功能体验清单（实际上线 · 了解/暂不使用）">
        {(open) => (open ? <ExperienceChecklistPanel /> : null)}
      </SubSection>
      <SubSection id="interaction-modes" label="新功能回退偏好（新旧交互二选一，兼容期限）">
        {(open) => (open ? <InteractionModePrefsPanel /> : null)}
      </SubSection>
      <SubSection id="service-status" label="实例服务状态（真实本地检测，无虚构可用率）">
        {(open) => (open ? <ServiceStatusPanel /> : null)}
      </SubSection>
      <SubSection id="error-runbooks" label="错误自助处理单（验证步骤 · 逐步记录 · 脱敏求助）">
        {(open) => (open ? <RunbookPanel /> : null)}
      </SubSection>
      <SubSection id="doc-feedback" label="帮助文档反馈（定位版本与锚点）">
        {(open) => (open ? <DocFeedbackPanel /> : null)}
      </SubSection>
      <SubSection id="module-cleanup" label="功能使用清理（本人关闭 · 数据去留）">
        {(open) => (open ? <ModuleCleanupPanel /> : null)}
      </SubSection>
    </div>
  )
}
