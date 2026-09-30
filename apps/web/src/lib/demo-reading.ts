/** demo-reading — NEW-360 移动端只读演示模式（隔离合成数据）。
 *
 * 演示模式展示阅读与管理两个界面样本，使用**完全隔离**的合成数据：
 * - 与真实账户零交集：不读取任何 store / API / localStorage 账户数据，
 *   全部内容来自本模块的字面量 fixture（URL 一律 example.com）；
 * - 不需要真实账户或生产截图——界面样本即代码渲染的合成数据；
 * - 只读：演示数据不提供任何会触发网络/变更的动作入口。
 */

import type { EntryDetail } from '../api/types'

export interface DemoSource {
  id: string
  title: string
  url: string
  category: string
  entryCount: number
  lastRefreshedAt: string
}

export interface DemoEntry extends EntryDetail {
  /** 合成摘要（列表展示）。 */
  snippet: string
}

export const DEMO_MODE_BANNER =
  '演示模式 · 只读 · 全部为合成数据，与真实账户和订阅无关'

export const DEMO_SOURCES: readonly DemoSource[] = [
  {
    id: 'demo-src-1',
    title: '晨间科技简报（演示）',
    url: 'https://example.com/feeds/tech-morning.xml',
    category: '科技（演示）',
    entryCount: 128,
    lastRefreshedAt: '10 分钟前',
  },
  {
    id: 'demo-src-2',
    title: '城市生活周刊（演示）',
    url: 'https://example.com/feeds/city-weekly.xml',
    category: '生活（演示）',
    entryCount: 64,
    lastRefreshedAt: '1 小时前',
  },
  {
    id: 'demo-src-3',
    title: '远航播客笔记（演示）',
    url: 'https://example.com/feeds/voyage-podcast.xml',
    category: '播客（演示）',
    entryCount: 32,
    lastRefreshedAt: '3 小时前',
  },
] as const

const READING_ARTICLE_HTML = `
<h2>什么是「只读演示」</h2>
<p>你正在看到的是 LumiRSS 的<strong>演示模式</strong>：这一页的全部
内容——来源、文章、数字——都是合成的示例数据，与任何真实账户、
订阅或服务器状态无关。</p>
<h2>演示模式能做什么</h2>
<p>演示模式用于体验阅读界面的排版与交互：切换文章、浏览目录、
查看媒体占位。所有会改动真实数据的操作（标已读、收藏、抓取、
同步）在演示模式里都不存在入口。</p>
<blockquote>合成数据的好处是零风险：随意浏览，不会留下任何痕迹。</blockquote>
<h2>如何退出</h2>
<p>点击页面底部的「退出演示模式」即可返回。演示状态只存在于当前
会话，不会被记住。</p>`

export const DEMO_ENTRIES: readonly DemoEntry[] = [
  {
    entryRef: 'demo:e1',
    title: '演示文章：为什么阅读器要「源优先」',
    feedTitle: '晨间科技简报（演示）',
    feedUrl: 'https://example.com/feeds/tech-morning.xml',
    author: '示例作者·甲',
    contentHtml: READING_ARTICLE_HTML,
    contentText: '你正在看到的是 LumiRSS 的演示模式。',
    publishedAt: '2026-09-28T08:00:00Z',
    crawledAt: '2026-09-28T08:05:00Z',
    url: 'https://example.com/articles/source-first',
    read: false,
    starred: false,
    snippet: '源优先意味着上游状态是唯一事实源……（合成摘要）',
  },
  {
    entryRef: 'demo:e2',
    title: '演示文章：把播客转成可检索的文字',
    feedTitle: '远航播客笔记（演示）',
    feedUrl: 'https://example.com/feeds/voyage-podcast.xml',
    author: '示例作者·乙',
    contentHtml: `<p>这是一篇<strong>合成</strong>的播客笔记示例。
    演示模式下媒体一律显示为占位，不会发起任何下载。</p>
    <audio src="https://example.com/media/demo-episode.mp3" controls></audio>`,
    contentText: '这是一篇合成的播客笔记示例。',
    publishedAt: '2026-09-27T19:30:00Z',
    crawledAt: '2026-09-27T19:35:00Z',
    url: 'https://example.com/articles/podcast-notes',
    read: true,
    starred: false,
    snippet: '转写、分章、要点抽取……（合成摘要）',
  },
  {
    entryRef: 'demo:e3',
    title: '演示文章：城市市集指南（含图示例）',
    feedTitle: '城市生活周刊（演示）',
    feedUrl: 'https://example.com/feeds/city-weekly.xml',
    author: '示例作者·丙',
    contentHtml: `<p>本篇演示<strong>图片占位</strong>：演示模式的图片
    不会加载，也不会消耗流量。</p>
    <img src="https://example.com/images/demo-market.jpg" alt="合成示例图">`,
    contentText: '本篇演示图片占位。',
    publishedAt: '2026-09-26T10:00:00Z',
    crawledAt: '2026-09-26T10:03:00Z',
    url: 'https://example.com/articles/city-market',
    read: false,
    starred: true,
    snippet: '周末市集、摊位与人流……（合成摘要）',
  },
] as const
