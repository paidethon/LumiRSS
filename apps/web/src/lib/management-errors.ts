/** 0013 Gate 3/4：订阅管理 + OPML 的稳定错误 type → 诚实文案。
 *
 * BFF 的 error.message 是英文技术细节，UI 只显示 type 映射的中文文案；
 * 未知 type 一律安全 fallback，不透传上游文本。只描述有真实依据的
 * 状态（上游没给的信号不编造）。 */

export interface ManagementErrorText {
  title: string
  detail: string | null
}

export function managementErrorText(error: unknown): ManagementErrorText {
  const type = (error as { type?: string } | null)?.type
  switch (type) {
    case 'category_not_found':
      return { title: '该分类已不存在，请刷新后重试。', detail: null }
    case 'subscription_not_found':
      return { title: '该订阅已不存在，请刷新后重试。', detail: null }
    case 'category_label_conflict':
      return { title: '这个名字已被其他分类使用。', detail: null }
    case 'default_category_immutable':
      return { title: '默认分类由 FreshRSS 管理，无法重命名。', detail: null }
    case 'invalid_category_label':
      return { title: '分类名需为 1–128 个字符，且不含 “/”。', detail: null }
    case 'network_error':
      return { title: '无法连接到服务器，请稍后重试。', detail: null }
    // 0013 Gate 4：FreshRSS 健康相关（只报告请求真实返回的错误码）
    case 'connection_error':
      return {
        title: '无法连接 FreshRSS，请确认服务正在运行。',
        detail: null,
      }
    case 'authentication_error':
      return {
        title: 'FreshRSS 拒绝了凭据（API 密码可能已变更），请检查服务端配置。',
        detail: null,
      }
    case 'configuration_error':
      return {
        title: 'BFF 缺少 FreshRSS 连接配置，请联系服务端管理员。',
        detail: null,
      }
    case 'upstream_error':
      return { title: 'FreshRSS 返回了异常响应，请稍后重试。', detail: null }
    // 0013 Gate 4：OPML
    case 'opml_invalid':
      return { title: '文件不是有效的 OPML（无法解析或缺少正文）。', detail: null }
    case 'opml_too_large':
      return { title: 'OPML 文件超过 2 MiB 上限。', detail: null }
    case 'opml_too_many_feeds':
      return { title: 'OPML 中的订阅源超过 500 个上限，请分批导入。', detail: null }
    case 'feed_rejected':
      return {
        title: 'FreshRSS 无法添加该订阅源（地址无效或不可达）。',
        detail: null,
      }
    default:
      return { title: '操作失败，请稍后重试。', detail: null }
  }
}
