/**
 * LumiRSS docs site — VitePress over the SAME Markdown that GitHub renders.
 * Single source: every page is a file already in docs/; nothing is copied.
 * Build doubles as the dead-link gate (`npm run docs:build`, no ignores).
 */

import { defineConfig } from 'vitepress'

// Deploy target is GitHub Pages PROJECT site → served under /LumiRSS/.
// Overridable for other targets; local dev/preview serve under the same
// base (VitePress dev+preview honor base), so what you preview is what
// Pages serves.
const base = process.env.DOCS_BASE || '/LumiRSS/'

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
  base,
  rewrites: {
    // docs/README.md is the docs homepage on GitHub AND the site home —
    // one source, no index copy.
    'README.md': 'index.md',
  },
  head: [
    // head entries are NOT base-prefixed by VitePress — build the
    // absolute path ourselves.
    ['link', { rel: 'icon', type: 'image/svg+xml', href: `${base}logo.svg` }],
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
        // LocalSearchOptions.miniSearch — the custom CJK tokenizer was
        // previously nested under a non-existent `options.options`
        // wrapper, so MiniSearch never saw it and every CJK char ran
        // through the default whitespace tokenizer (pool #49: verified
        // against vitepress default-theme.d.ts).
        miniSearch: {
          // MiniSearch 构造参数：换掉按空白分词的默认 tokenizer，
          // 中文按单字索引（实测默认分词搜不到中文）。
          options: { tokenize },
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
      { text: '历史', link: '/history/milestones', activeMatch: '/(audits|history|upstream)/' },
    ],
    sidebar: {
      '/': [
        {
          text: '开始',
          items: [
            { text: '快速上手', link: '/getting-started' },
            // README.md is rewritten to index.md — the /README route no
            // longer exists at runtime (dead-link gate checks source
            // files, not rewritten routes, so it never caught this).
            { text: '文档导航', link: '/' },
          ],
        },
        {
          text: '使用（How-to）',
          items: [
            { text: '部署 / 升级 / 回滚', link: '/how-to/deploy' },
            { text: '邀请成员（运营者）', link: '/how-to/invite-members' },
            { text: '备份与恢复', link: '/how-to/backup-restore' },
            { text: '故障排查', link: '/how-to/troubleshoot' },
          ],
        },
        {
          text: '参考（Reference）',
          items: [
            { text: '配置键', link: '/reference/configuration' },
            { text: '测试与 CI', link: '/reference/testing' },
            { text: '性能与负载', link: '/reference/performance' },
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
            { text: '邀请制多账户（ADR 0005）', link: '/decisions/0005-invite-multi-account' },
            { text: '设计系统', link: '/design/design-system' },
          ],
        },
        { text: 'Roadmap', link: '/ROADMAP' },
        {
          text: ARCHIVE,
          collapsed: true,
          items: [
            { text: 'Recovery 审计账本（冻结）', link: '/audits/phase2-recovery' },
            { text: '历史里程碑', link: '/history/milestones' },
            { text: '上游引用与许可', link: '/upstream/UPSTREAMS' },
          ],
        },
      ],
    },
  },
})
