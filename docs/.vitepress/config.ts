/**
 * LumiRSS docs site — VitePress over the SAME Markdown that GitHub renders.
 * Single source: every page is a file already in docs/; nothing is copied.
 * Build doubles as the dead-link gate (`npm run docs:build`, no ignores).
 */

import { execSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { defineConfig, type HeadConfig } from 'vitepress'

// Production docs site (doc.oouo.top) is served at the domain root, so the
// production build is base '/'. The GitHub Pages project-site mirror needs
// '/LumiRSS/' — that target sets DOCS_BASE explicitly (pinned in CI). There
// is deliberately no project-URL default: a wrong silent default is what
// broke doc.oouo.top assets/links (everything pointed at /LumiRSS/* while
// the server serves '/'). Local dev/preview run at '/' like production.
const base = process.env.DOCS_BASE ?? '/'

const SITE_URL = 'https://doc.oouo.top'

// Build provenance (§16: version footer must come from the repo/CI, never
// hand-copied). VERSION is the single version source; commit comes from the
// CI environment with a local git fallback; the date is the build date.
function readVersion(): string {
  try {
    return readFileSync(fileURLToPath(new URL('../../VERSION', import.meta.url)), 'utf8').trim()
  } catch {
    return 'unknown'
  }
}
function readCommit(): string {
  const fromCI = process.env.GITHUB_SHA
  if (fromCI) return fromCI.slice(0, 7)
  try {
    return execSync('git rev-parse --short HEAD').toString().trim()
  } catch {
    return 'unknown'
  }
}
const buildInfo = {
  version: readVersion(),
  commit: readCommit(),
  date: new Date().toISOString().slice(0, 10),
}

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

// Per-page canonical + OpenGraph against the production host. head entries
// are NOT base-prefixed by VitePress, so build the absolute URL ourselves.
function pageHead(pageData: { relativePath: string; title: string; description: string }): HeadConfig[] {
  const route = pageData.relativePath === 'index.md' ? '' : `/${pageData.relativePath.replace(/\.md$/, '')}`
  const url = `${SITE_URL}${route}/`.replace(/index\.html/, '')
  return [
    ['link', { rel: 'canonical', href: url }],
    ['meta', { property: 'og:url', content: url }],
    ['meta', { property: 'og:site_name', content: 'LumiRSS' }],
    ['meta', { property: 'og:type', content: 'website' }],
    ['meta', { property: 'og:title', content: pageData.title }],
    ['meta', { property: 'og:description', content: pageData.description }],
    ['meta', { property: 'og:locale', content: 'zh_CN' }],
  ]
}

export default defineConfig({
  lang: 'zh-CN',
  title: 'LumiRSS',
  description: '邀请制多账户、自托管、source-first 的信息阅读器',
  cleanUrls: true,
  base,
  sitemap: { hostname: SITE_URL },
  // LEGAL 存档（许可审计/来源归档）保留在仓库供 GitHub 渲染与合规引用，
  // 但不进入文档站：它们不是面向用户/开发者的活跃文档。
  srcExclude: ['upstream/**'],
  // 唯一豁免：上游功能对照矩阵是 docs/public/reference/ 下的独立 HTML
  // 资产（离线单文件，非 VitePress 页面），md 里以绝对路径链接引用，
  // 构建期无法解析为页面——运行时路径经 public/ 拷贝后成立。
  ignoreDeadLinks: [/^\/reference\/upstream-feature-matrix(\.html)?$/],
  head: [
    // head entries are NOT base-prefixed by VitePress — build the
    // absolute path ourselves.
    ['link', { rel: 'icon', type: 'image/svg+xml', href: `${base}logo.svg` }],
  ],
  transformHead: ({ pageData }) => pageHead(pageData),
  vite: {
    define: {
      __LUMI_DOCS_BUILD__: JSON.stringify(buildInfo),
    },
  },
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
        // LocalSearchOptions.miniSearch — MiniSearch 构造参数：换掉按空白
        // 分词的默认 tokenizer，中文按单字索引（实测默认分词搜不到中文）。
        miniSearch: {
          options: { tokenize },
        },
      },
    },
    socialLinks: [{ icon: 'github', link: 'https://github.com/paidethon/LumiRSS' }],
    nav: [
      { text: '指南', link: '/getting-started', activeMatch: '/(getting-started|usage)' },
      { text: '部署', link: '/operations' },
      { text: '配置', link: '/configuration' },
      { text: '架构', link: '/architecture', activeMatch: '/(architecture|design-system|upstreams)' },
      { text: 'Roadmap', link: '/roadmap' },
      { text: 'GitHub', link: 'https://github.com/paidethon/LumiRSS' },
    ],
    sidebar: [
      {
        text: '开始',
        items: [
          { text: '快速开始', link: '/getting-started' },
          { text: '使用指南', link: '/usage' },
        ],
      },
      {
        text: '运维',
        items: [
          { text: '部署与运维', link: '/operations' },
          { text: '配置参考', link: '/configuration' },
        ],
      },
      {
        text: '开发',
        items: [
          { text: '架构', link: '/architecture' },
          { text: '设计系统', link: '/design-system' },
          { text: '开发指南', link: '/development' },
        ],
      },
      {
        text: '项目',
        items: [
          { text: 'Roadmap', link: '/roadmap' },
          { text: '上游对照', link: '/upstreams' },
        ],
      },
    ],
    footer: {
      message: '基于 AGPL-3.0 发布',
      copyright: 'LumiRSS · Source-first information reader',
    },
  },
})
