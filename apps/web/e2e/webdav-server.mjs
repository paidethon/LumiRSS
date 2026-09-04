/** 测试专用一次性 WebDAV 服务器（仅 e2e 使用；实现 MKCOL/PUT/GET/
 * PROPFIND/DELETE 的最小子集）。数据保存在内存中，关闭服务即丢弃。
 *
 * 用法（进程内）：createWebDavServer(username, password).listen(port)
 * 认证：HTTP Basic；凭据错误返回 401。
 */

import http from 'node:http'

export function createWebDavServer(user = 'smoketest', pass = 'smoke-pass') {
  /** 内存文件系统：Map<fullPath, Buffer> */
  const files = new Map()

  function checkAuth(req) {
    const header = req.headers.authorization ?? ''
    if (!header.startsWith('Basic ')) return false
    const decoded = Buffer.from(header.slice(6), 'base64').toString('utf8')
    const [name, ...rest] = decoded.split(':')
    return name === user && rest.join(':') === pass
  }

  function xmlEscape(s) {
    return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  }

  return http.createServer((req, res) => {
    if (!checkAuth(req)) {
      res.writeHead(401, { 'WWW-Authenticate': 'Basic realm="e2e"' })
      res.end()
      return
    }
    const path = decodeURIComponent(req.url.replace(/\/+$/, '')) || '/'
    if (req.method === 'MKCOL') {
      files.set(`${path}/`, Buffer.alloc(0))
      res.writeHead(201)
      res.end()
    } else if (req.method === 'PUT') {
      const chunks = []
      req.on('data', (c) => chunks.push(c))
      req.on('end', () => {
        files.set(path, Buffer.concat(chunks))
        res.writeHead(201)
        res.end()
      })
    } else if (req.method === 'GET') {
      const data = files.get(path)
      if (data === undefined) {
        res.writeHead(404)
        res.end()
      } else {
        res.writeHead(200, { 'Content-Type': 'application/octet-stream' })
        res.end(data)
      }
    } else if (req.method === 'PROPFIND') {
      const chunks = []
      req.on('data', (c) => chunks.push(c))
      req.on('end', () => {
        const prefix = path === '/' ? '' : path
        const children = [...files.entries()]
          .filter(([name]) => name.startsWith(`${prefix}/`) && !name.slice(prefix.length + 1).includes('/'))
          .filter(([name]) => !name.endsWith('/'))
        const body = `<?xml version="1.0"?><d:multistatus xmlns:d="DAV:">${children
          .map(
            ([name, data]) =>
              `<d:response><d:href>${xmlEscape(name)}</d:href>` +
              '<d:propstat><d:prop><d:getcontentlength>' +
              data.length +
              '</d:getcontentlength></d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>',
          )
          .join('')}</d:multistatus>`
        res.writeHead(207, { 'Content-Type': 'application/xml' })
        res.end(body)
      })
    } else if (req.method === 'DELETE') {
      const deleted = files.delete(path)
      res.writeHead(deleted ? 204 : 404)
      res.end()
    } else {
      res.writeHead(405)
      res.end()
    }
  })
}
