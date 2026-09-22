/** E2E globalSetup — session 模式栈的可选预登录。
 *
 * 背景（Round 2 审计发现）：desktop/mobile journeys 最早只对 basic-auth
 * 栈跑过——Gate 8 的 session 模式栈上浏览器停在登录页，所有依赖
 * 应用壳的用例集体失败。设置 LUMIRSS_E2E_LOGIN（= 登录口令）时，
 * setup 先用 API 登录一次，把 session cookie 以 storageState 注入
 * 所有后续 context；不设置（basic 模式 / CI 静态模式）时行为不变。
 */

import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import type { FullConfig } from '@playwright/test'
import { chromium } from '@playwright/test'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const STATE_FILE = path.join(HERE, '.auth', 'state.json')

export default async function globalSetup(config: FullConfig): Promise<void> {
  const password = process.env.LUMIRSS_E2E_LOGIN
  if (!password) return
  const baseURL = config.projects[0]?.use?.baseURL ?? 'http://127.0.0.1'

  const browser = await chromium.launch()
  try {
    const context = await browser.newContext({ baseURL })
    // 0067 多账户契约：用户名+密码登录（默认 owner；可用
    // LUMIRSS_E2E_LOGIN_USER 覆盖为其它成员账号做隔离走查）。
    const username = process.env.LUMIRSS_E2E_LOGIN_USER ?? 'owner'
    const response = await context.request.post('/api/v1/auth/login', {
      data: { username, password },
      headers: { Origin: baseURL },
    })
    if (!response.ok()) {
      throw new Error(`E2E 预登录失败：HTTP ${response.status()}（检查 LUMIRSS_E2E_LOGIN 与栈的 auth 模式）`)
    }
    fs.mkdirSync(path.dirname(STATE_FILE), { recursive: true })
    await fs.promises.writeFile(STATE_FILE, JSON.stringify(await context.storageState()))
    await context.close()
  } finally {
    await browser.close()
  }
}
