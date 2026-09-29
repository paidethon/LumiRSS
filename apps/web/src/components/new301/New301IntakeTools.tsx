/** NEW-301..310 组合入口 — API 来源、Webhook 与自动接入工具台。

- 两级情境展开（MASTER §6）：折叠态只渲染开关、零查询；展开后才
  挂载对应子面板（子面板自己的 useEffect 才发请求）；
- 来源选择器为全组共享（选择器本身不产生请求）；
- 挂载点：设置 → API 来源（ApiSourcesSection 底部）。 */

import { useCallback, useEffect, useState, type ReactElement } from 'react'
import {
  listSourceRefs,
  type ApiSourceRef,
} from '../../api/new301'
import { errorText, StatusLine } from '../new271/panel'
import { SubSection } from '../new271/panel'
import {
  IntakeQuotaPanel,
  MappingSamplePanel,
  PaginationProbePanel,
  SchemaPausePanel,
  type SourceScope,
  SourcePicker,
} from './parts-a'
import {
  DeadLetterPanel,
  SigningKeyAdminPanel,
  WebhookInboxPanel,
} from './parts-b'
import {
  DeliveryReceiptPanel,
  OutSubscriptionPanel,
  TransferBundlePanel,
} from './parts-c'

export function New301IntakeTools(): ReactElement {
  const [sources, setSources] = useState<ApiSourceRef[]>([])
  const [selected, setSelected] = useState('')
  const [error, setError] = useState('')

  const refresh = useCallback(async () => {
    try {
      const listed = await listSourceRefs()
      setSources(listed.items)
      setSelected((current) =>
        current !== '' ? current : first_uuid_of(listed) ?? '',
      )
    } catch (err) {
      setError(errorText(err))
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const chosen: SourceScope = {
    source: sources.find((one) => one.uuid === selected),
    sources: sources,
    onPick: setSelected,
    idPrefix: 'new301-shared',
  }

  return (
    <div data-new301-tools="" className="mt-2 flex flex-col gap-2 border-t border-[var(--lumi-border)] pt-3">
      <p className="text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
        接入工具台：字段映射样本、分页试抓、写暂停确认、每日配额、
        Webhook 收发与配置转移（子区折叠时不发任何请求）。
      </p>
      {error !== '' && <StatusLine tone="error">{error}</StatusLine>}
      <SourcePicker {...chosen} />
      <SubSection id="new301-mapping" label="NEW-301 字段映射编辑器（JSON 样本试映射）">
        <MappingSamplePanel sourceUuid={selected || undefined} />
      </SubSection>
      <SubSection id="new302-probe" label="NEW-302 分页试抓台（受限页数验证契约）">
        <PaginationProbePanel sourceUuid={selected || undefined} />
      </SubSection>
      <SubSection id="new306-pause" label="NEW-306 抓取变更预警（写暂停确认）">
        <SchemaPausePanel sourceUuid={selected || undefined} />
      </SubSection>
      <SubSection id="new307-quota" label="NEW-307 自动接入来源配额（每日条目数）">
        <IntakeQuotaPanel sourceUuid={selected || undefined} />
      </SubSection>
      <SubSection id="new303-inbox" label="NEW-303 Webhook 接收收件箱（先审阅再入库）">
        <WebhookInboxPanel />
      </SubSection>
      <SubSection id="new305-dead" label="NEW-305 接入死信处理页（脱敏重放）">
        <DeadLetterPanel />
      </SubSection>
      <SubSection id="new304-keys" label="NEW-304 签名钥轮换（管理员）">
        <SigningKeyAdminPanel />
      </SubSection>
      <SubSection id="new308-out" label="NEW-308 外发 Webhook 事件订阅">
        <OutSubscriptionPanel />
      </SubSection>
      <SubSection id="new309-receipts" label="NEW-309 Webhook 投递回执">
        <DeliveryReceiptPanel />
      </SubSection>
      <SubSection id="new310-transfer" label="NEW-310 接入配置转移包（无秘密）">
        <TransferBundlePanel />
      </SubSection>
    </div>
  )
}

function first_uuid_of(listed: { items: ApiSourceRef[] }): string | undefined {
  return listed.items.length > 0 ? listed.items[0].uuid : undefined
}
