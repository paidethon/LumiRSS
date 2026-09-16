/** 产品内帮助链接（pool #56）：少数高频故障 → 现有文档的准确锚点。
 *
 * 用 GitHub main 分支链接而不是 Pages 站点：文档站未部署/落后时链接
 * 依然有效，且内容与当前仓库版本一致。不复制文档内容进产品——单一
 * 真源仍在 docs/。 */

export const DOCS_BASE =
  'https://github.com/paidethon/LumiRSS/blob/main/docs'

export const DOCS_LINKS = {
  /** 来源/条目失效的排查（troubleshoot「常见症状」表） */
  troubleshootSymptoms: `${DOCS_BASE}/how-to/troubleshoot.md#常见症状`,
  /** 本地（浏览器）翻译不可用的根因与支持范围 */
  translationLocalUnsupported: `${DOCS_BASE}/research/local-translation.md#2-本地翻译无法调用的根因证据链非猜测`,
  /** WebDAV 备份配置与失败处置 */
  webdavBackup: `${DOCS_BASE}/how-to/backup-restore.md#webdav`,
} as const
