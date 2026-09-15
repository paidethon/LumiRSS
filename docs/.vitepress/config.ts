/**
 * LumiRSS docs site — VitePress over the SAME Markdown that GitHub renders.
 * Single source: every page is a file already in docs/; nothing is copied.
 * Build doubles as the dead-link gate (`npm run docs:build`, no ignores).
 */

import { defineConfig } from 'vitepress'

/** CJK-aware tokenizer: split latin/digit words, and CJK text into
 * single characters (whitespace tokenization would make whole Chinese
 * sentences unfindable). Mirrors the minisearch usage in VitePress. */
function tokenize(text: string): string[] {
  const tokens: string[] = []
  const cjk = /[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]/
  let word = ''
  for (const ch of text.toLowerCase()) {
    if (cjk.test(ch)) {
      if (word) tokens.push(word)
      word = ''
      tokens.push(ch)
    } else if (/[\wáàéèíìóòúùüñç]/i.test(ch)) {
      word += ch
    } else {
      if (word) tokens.push(word)
      word = ''
    }
  }
  if (word) tokens.push(word)
  return tokens
}

const ARCHIVE = '历史与研究（存档）'

export default defineConfig({
  lang: 'zh-CN',
  title: 'LumiRSS',
  description: '单用户、自托管、source-first 的信息阅读器',
  cleanUrls: true,
  rewrites: {
    // docs/README.md is the docs homepage on GitHub AND the site home —
    // one source, no index copy.
    'README.md': 'index.md',
  },
  head: [
    ['link', { rel: 'icon', type: 'image/svg+xml', href: '/logo.svg' }],
  ],
  themeConfig: {
    logo: '/logo.svg',
    siteTitle: 'LumiRSS',
    outline: { level: [2, 3], label: '本页' },
    docFooter: { prev: '上一篇', next: '下一篇' },
    lastUpdated: { text: '最后更新', formatOptions: { dateStyle: 'medium' } },
    search: {
      provider: 'local',
      options: {
        translations: {
          button: { buttonText: '搜索文档', buttonAriaLabel: '搜索文档' },
          modal: {
            noResultsText: '没有结果',
            resetButtonTitle: '清除',
            footer: { selectText: '选择', navigateText: '切换', closeText: '关闭' },
          },
        },
        options: {
          miniSearch: {
            // MiniSearch 构造参数：换掉按空白分词的默认 tokenizer，
            // 中文按单字索引（实测默认分词搜不到中文）。
            options: { tokenize },
          },
        },
      },
    },
    socialLinks: [{ icon: 'github', link: 'https://github.com/paidethon/LumiRSS' }],
    nav: [
      { text: '开始', link: '/getting-started' },
      { text: '使用', link: '/how-to/deploy' },
      { text: '配置', link: '/reference/configuration' },
      { text: '架构', link: '/explanation/architecture' },
      { text: 'Roadmap', link: '/ROADMAP' },
      { text: '存档', link: '/research/phase2/00-platform-architecture', activeMatch: '/(research|audits|history|upstream)/' },
    ],
    sidebar: {
      '/': [
        {
          text: '开始',
          items: [
            { text: '快速上手', link: '/getting-started' },
            { text: '文档导航', link: '/README' },
          ],
        },
        {
          text: '使用（How-to）',
          items: [
            { text: '部署 / 升级 / 回滚', link: '/how-to/deploy' },
            { text: '备份与恢复', link: '/how-to/backup-restore' },
            { text: '故障排查', link: '/how-to/troubleshoot' },
          ],
        },
        {
          text: '参考（Reference）',
          items: [
            { text: '配置键', link: '/reference/configuration' },
            { text: '测试与 CI', link: '/reference/testing' },
          ],
        },
        {
          text: '解释（Explanation）',
          items: [
            { text: '系统架构', link: '/explanation/architecture' },
            { text: '全局搜索原理', link: '/explanation/search' },
            { text: '复用与自研边界', link: '/explanation/reuse-policy' },
          ],
        },
        {
          text: '产品与决策',
          items: [
            { text: '产品需求（PRD）', link: '/product/PRD' },
            { text: '架构决策（ADR）', link: '/decisions/0001-freshrss-owns-rss-state' },
            { text: '设计系统', link: '/design/design-system' },
          ],
        },
        { text: 'Roadmap', link: '/ROADMAP' },
        {
          text: ARCHIVE,
          collapsed: true,
          items: [
            { text: 'Phase 2 研究', link: '/research/phase2/00-platform-architecture' },
            { text: '其他研究报告', link: '/research/local-translation' },
            { text: 'Recovery 审计账本', link: '/audits/phase2-recovery' },
            { text: '历史里程碑', link: '/history/milestones' },
            { text: '上游引用与许可', link: '/upstream/UPSTREAMS' },
          ],
        },
      ],
    },
  },
})
