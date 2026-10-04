/** 产品内帮助链接（pool #56）：少数高频故障 → 现有文档的准确锚点。
 *
 * 链接指向正式文档站 doc.oouo.top（GitHub Actions 每次 docs/** 变更自动
 * 构建部署，CI 里逐路由 production smoke 验证）。不复制文档内容进产品
 * ——单一真源仍在 docs/，站点就是它的发布形态。 */

export const DOCS_BASE = 'https://doc.oouo.top'

export const DOCS_LINKS = {
  /** 来源/条目失效的排查（operations「故障排查」表） */
  troubleshootSymptoms: `${DOCS_BASE}/operations#故障排查`,
  /** 本地（浏览器/自托管）翻译已移除的决策与非目标 */
  translationLocalUnsupported: `${DOCS_BASE}/roadmap#deferred`,
  /** WebDAV 备份配置与失败处置（operations「备份与恢复」敏感性边界） */
  webdavBackup: `${DOCS_BASE}/operations#敏感性`,
} as const
