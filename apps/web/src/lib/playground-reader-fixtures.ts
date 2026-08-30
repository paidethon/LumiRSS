/** Playground Reader fixtures — 0012 Gate 11（dev-only，随 Playground
 * 一起排除出生产 bundle）。
 *
 * 八个场景（Spec 冻结清单）：english-long / chinese-long / mixed /
 * code-heavy / images / malicious / no-html / long-title。
 * 恶意 fixture 用来肉眼验证「transforms 之后危险内容仍被清洗」。 */

import type { EntryDetail } from '../api/types'

const entryRef = 'e1.cGxheWdyb3VuZC1maXh0dXJl'

export interface ReaderFixture {
  id: string
  label: string
  detail: EntryDetail
}

const LONG_TITLE =
  '这是一条非常非常长的文章标题用来验证 Reader 头部的换行与截断行为是否在移动端与桌面端都保持稳定不产生横向溢出'

const englishLong = `
<p>The craft of reading has always been shaped by its tools. From scrolls
to codices, from the printing press to the glowing rectangle you hold
tonight, each medium quietly rewires how we pay attention. A reader
application is therefore never merely a viewer; it is an argument about
what deserves your focus.</p>
<p>Consider the humble paragraph. In print, its indentation and spacing
carry rhythm. On the web, we mostly lost that music — paragraphs became
flush-left blocks separated by bare margins, uniform as parking lots.
Restoring typographic rhythm for long-form reading is not nostalgia; it
is ergonomics. Eyes tire less when the page breathes.</p>
<p>And so we tune line height, measure, and contrast. We let readers
choose serif or sans. We hang punctuation at the margin like coats on
hooks. None of this is decoration. All of it is respect for the person
who chose to read ten thousand words on a screen instead of doing
almost anything else.</p>
<p><strong>Reading time estimation</strong>, <em>bionic emphasis</em>,
and simplified-traditional conversion each add a layer of presentation.
The untrusted article HTML beneath them must remain exactly that:
untrusted, sanitized, inert until proven safe.</p>
`.repeat(3)

const chineseLong = `
<p>中文长文的阅读体验，与英文有着截然不同的排版诉求。段落之间靠首行
缩进区分，而不是段间距；标点可以悬挂在行首边缘，让文字块更加齐整；
简体与繁体的转换，往往发生在阅读者的一念之间。</p>
<p>我们熟悉的中文书籍排版，是从雕版印刷时代延续下来的传统。两个字
的首行缩进，是一个视觉信号：新的一段开始了。屏幕阅读继承了这一习惯，
却常常把它丢掉——大多数阅读器只提供段间距开关，无法真正还原纸书的
阅读节奏。</p>
<p>标点悬挂（hanging punctuation）是另一项被遗忘的技艺。当一行文字
以逗号或句号结尾时，把标点悬挂到版心之外，可以让左右边缘保持视觉
上的整齐。浏览器对这一特性的支持仍在演进，因此我们采用渐进增强：
支持的浏览器获得更好的排版，不支持的浏览器优雅退回。</p>
<p>阅读时间估算也需要中文思维。以英文词数估算一篇纯中文文章，结果
永远是零分钟——这显然是荒谬的。汉字有自己的阅读速度，中英混排的
文章需要两种速度加权计算。</p>
<blockquote>排版不是装饰，是对阅读者的尊重。</blockquote>
`.repeat(3)

const mixed = `
<p>阅读器的 typography 需要同时照顾中英文。这是一段 mixed 内容：
中文与 English 交替出现，用来验证 bionic 词首强调只作用于 Latin words、
CJK 字符保持原样的边界行为。</p>
<p>OpenCC 的简繁转换只处理 text node，code 与 URL 不受影响：
<code>let 变量名 = "value"</code>，以及链接
<a href="https://example.com/中文路径">example.com</a>。</p>
<p>阅读时间：约 6 分钟（中英混排加权估算）。</p>
`

const codeHeavy = `
<p>下面是一段 TypeScript 代码，用于验证 Shiki 按需高亮：</p>
<pre><code class="language-typescript">interface Entry {
  entryRef: string
  title: string
  read: boolean
}

async function markRead(entry: Entry): Promise&lt;void&gt; {
  const res = await fetch(\`/api/v1/entries/\${entry.entryRef}/state\`, {
    method: 'PATCH',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ read: true }),
  })
  if (!res.ok) throw new Error(\`HTTP \${res.status}\`)
}</code></pre>
<p>再来一段 Python：</p>
<pre><code class="language-python">def estimate_reading_time(text: str) -> dict:
    cjk = sum(1 for ch in text if '\u4e00' <= ch <= '\u9fff')
    latin = len([w for w in text.split() if w.isascii()])
    minutes = max(1, (cjk // 300) + (latin // 220))
    return {"minutes": minutes, "cjk": cjk, "latin": latin}</code></pre>
<p>未识别语言应保持 plaintext：</p>
<pre><code class="language-brainfuck">++++++++[&gt;++++[&gt;++&gt;+++&gt;+++&gt;+&lt;&lt;&lt;&lt;-]&gt;+&gt;+&gt;-&gt;&gt;+[&lt;]&lt;-]</code></pre>
`

const images = `
<p>图片模式验证：超大图片不应撑破 Reader 容器。</p>
<figure>
  <img src="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='2400' height='1200'%3E%3Crect width='2400' height='1200' fill='%236d78e8'/%3E%3C/svg%3E" alt="超大测试图" />
  <figcaption>2400px 宽的占位图（max-width: 100% 约束）</figcaption>
</figure>
<p>图片之后的段落，用于验证首行缩进在图片后的表现（同为顶层段落，
行为应一致且无异常）。</p>
<table>
  <thead><tr><th>模式</th><th>效果</th></tr></thead>
  <tbody>
    <tr><td>all</td><td>全部显示</td></tr>
    <tr><td>grayscale</td><td>灰度报纸风</td></tr>
    <tr><td>hidden</td><td>隐藏（纯文字）</td></tr>
  </tbody>
</table>
`

const malicious = `
<p onclick="alert(1)">这一段带有 onclick 属性，渲染后应被移除。</p>
<img src=x onerror="alert(1)">
<a href="javascript:alert(1)">javascript: 链接不应存活</a>
<iframe src="https://evil.example"></iframe>
<style>body { background: red }</style>
<form action="https://evil.example"><input type="text"></form>
<svg><script>alert(1)</script></svg>
<p>如果以上危险内容全部不可见或被清洗，且这段文字正常显示，安全边界即生效。</p>
`

export const READER_FIXTURES: ReaderFixture[] = [
  {
    id: 'english-long',
    label: '英文长文',
    detail: mk('English Long-form', englishLong),
  },
  {
    id: 'chinese-long',
    label: '中文长文',
    detail: mk('中文长文排版验证', chineseLong),
  },
  { id: 'mixed', label: '中英混排', detail: mk('Mixed 中英混排', mixed) },
  { id: 'code-heavy', label: '代码密集', detail: mk('Code Heavy', codeHeavy) },
  { id: 'images', label: '图片/表格', detail: mk('Images & Tables', images) },
  {
    id: 'malicious',
    label: '恶意 HTML',
    detail: mk('Malicious HTML Regression', malicious),
  },
  {
    id: 'no-html',
    label: '无 HTML 正文',
    detail: {
      entryRef,
      title: '纯文本文章',
      feedTitle: 'Fixture Feed',
      author: null,
      url: 'https://example.com/plain',
      publishedAt: '2026-08-30T12:00:00Z',
      read: false,
      starred: false,
      contentText:
        '这是 contentText 纯文本分支：当文章没有 HTML 正文时，Reader 退化为 pre-wrap 纯文本渲染，不包装成 HTML。',
      contentHtml: null,
    },
  },
  {
    id: 'long-title',
    label: '超长标题',
    detail: mk(LONG_TITLE, '<p>超长标题的正文内容。</p>'),
  },
]

function mk(title: string, contentHtml: string): EntryDetail {
  return {
    entryRef,
    title,
    feedTitle: 'Fixture Feed',
    author: 'Lumi Fixtures',
    url: 'https://example.com/article',
    publishedAt: '2026-08-30T12:00:00Z',
    read: false,
    starred: false,
    contentText: '',
    contentHtml,
  }
}
