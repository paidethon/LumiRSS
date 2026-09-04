/** 测试专用一次性服务（进程内）：
 * - createFeedServer：极简 RSS/Atom feed 服务器（订阅即可拉到条目）；
 * - createAiMockServer：OpenAI 兼容 /chat/completions mock（0015/0016 契约）。
 * 两者均为 e2e 专用、内存态、进程结束即丢弃；凭据均为一次性假值。
 */

import http from 'node:http'

const RSS_XML = `<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<title>Lumi E2E Feed</title><link>https://e2e.example/</link>
<description>Deterministic feed for Playwright journeys</description>
<item><title>文章 alpha</title><link>https://e2e.example/alpha</link>
<guid>alpha</guid><pubDate>Mon, 01 Sep 2026 08:00:00 GMT</pubDate>
<description>&lt;p&gt;alpha 正文内容，用于 Reader 断言。&lt;/p&gt;</description></item>
<item><title>文章 beta</title><link>https://e2e.example/beta</link>
<guid>beta</guid><pubDate>Tue, 02 Sep 2026 08:00:00 GMT</pubDate>
<description>&lt;p&gt;beta 正文内容。&lt;/p&gt;</description></item>
<item><title>文章 gamma</title><link>https://e2e.example/gamma</link>
<guid>gamma</guid><pubDate>Wed, 03 Sep 2026 08:00:00 GMT</pubDate>
<description>&lt;p&gt;gamma 正文内容。&lt;/p&gt;</description></item>
</channel></rss>`

export function createFeedServer(port = 18083, host = '0.0.0.0') {
  const server = http.createServer((req, res) => {
    res.writeHead(200, { 'Content-Type': 'application/rss+xml; charset=utf-8' })
    res.end(RSS_XML)
  })
  return new Promise((resolve) => server.listen(port, host, () => resolve(server)))
}

/** OpenAI 兼容 mock：只实现 /v1/chat/completions，固定返回可断言文本。 */
export function createAiMockServer(port = 18082, host = '0.0.0.0') {
  const server = http.createServer((req, res) => {
    if (req.method !== 'POST' || !req.url.includes('/chat/completions')) {
      res.writeHead(404, { 'Content-Type': 'application/json' })
      res.end(JSON.stringify({ error: { message: 'not found' } }))
      return
    }
    const chunks = []
    req.on('data', (c) => chunks.push(c))
    req.on('end', () => {
      let question = ''
      try {
        const body = JSON.parse(Buffer.concat(chunks).toString('utf8'))
        const last = body.messages?.[body.messages.length - 1]?.content ?? ''
        question = typeof last === 'string' ? last : ''
      } catch {
        question = ''
      }
      const reply = `MOCK-AI-REPLY: ${question.slice(0, 80) || 'empty'}`
      res.writeHead(200, { 'Content-Type': 'application/json' })
      res.end(
        JSON.stringify({
          id: 'chatcmpl-mock',
          object: 'chat.completion',
          created: Math.floor(Date.now() / 1000),
          model: 'mock-model',
          choices: [
            {
              index: 0,
              message: { role: 'assistant', content: reply },
              finish_reason: 'stop',
            },
          ],
          usage: { prompt_tokens: 1, completion_tokens: 1, total_tokens: 2 },
        }),
      )
    })
  })
  return new Promise((resolve) => server.listen(port, host, () => resolve(server)))
}
