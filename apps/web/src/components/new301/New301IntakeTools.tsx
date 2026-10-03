/** 接入中心聚合入口 — Webhook 收件、外发事件订阅、投递回执与死信重试。
 *
 - 只在存在 ≥1 个 API 来源时由设置页挂出（聚合入口，默认折叠）；
 - 折叠态零请求：本组件仅在展开后挂载，各面板的请求在其自身
   useEffect 里发起；
 - 死信重试只在存在失败记录时显示（挂载时探测一次，空则整节隐藏）；
 - 来源级工具（字段映射 / 分页试抓 / 变更预警 / 配额）已移入
   ApiSourceDetailDrawer 的字段 / 抓取 tab；
 - new301 内部文件命名保留；用户可见文案一律自然语言。 */

import { useCallback, useEffect, useState, type ReactElement } from 'react'
import { new305Api, type DeadLetterRow } from '../../api/new301'
import { errorText, StatusLine } from '../new271/panel'
import { SubSection } from '../new271/panel'
import {
  DeadLetterPanel,
  WebhookInboxPanel,
} from './parts-b'
import {
  DeliveryReceiptPanel,
  OutSubscriptionPanel,
} from './parts-c'

/** 死信重试：只有存在失败记录才显示整节（先探测，空则不渲染）。 */
function DeadLetterSection(): ReactElement | null {
  const [letters, setLetters] = useState<DeadLetterRow[] | null>(null)
  const [error, setError] = useState('')

  const probe = useCallback(async () => {
    setError('')
    try {
      const listed = await new305Api.list()
      setLetters(listed.items)
    } catch (err) {
      setError(errorText(err))
      setLetters([])
    }
  }, [])

  useEffect(() => {
    void probe()
  }, [probe])

  if (error !== '') {
    return <StatusLine tone="error">死信探测失败：{error}</StatusLine>
  }
  if (letters === null || letters.length === 0) return null
  return (
    <SubSection id="intake-dead-letter" label="死信重试（脱敏重放）">
      <DeadLetterPanel />
    </SubSection>
  )
}

export function IntakeCenter(): ReactElement {
  return (
    <div data-intake-center="" className="mt-2 flex flex-col gap-2">
      <p className="text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
        接入中心：Webhook 收件与外发投递的审阅、订阅与回执；
        来源级设置在各来源的详情里。
      </p>
      <SubSection id="intake-webhook-inbox" label="Webhook 收件箱（先审阅再入库）">
        <WebhookInboxPanel />
      </SubSection>
      <SubSection id="intake-out-subscription" label="外发事件订阅">
        <OutSubscriptionPanel />
      </SubSection>
      <SubSection id="intake-delivery-receipt" label="投递回执">
        <DeliveryReceiptPanel />
      </SubSection>
      <DeadLetterSection />
    </div>
  )
}
