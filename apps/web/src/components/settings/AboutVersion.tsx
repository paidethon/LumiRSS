/** AboutVersion — 关于页构建溯源（Web/BFF 版本错配诊断）。
 *
 * 生产 404 排障的教训：浏览器里的 Web 是新构建、线上 BFF 可能是旧镜像，
 * 双方都说不清自己是谁。现在 Web 构建注入 VITE_GIT_COMMIT（vite.config
 * define），BFF 暴露 GET /api/v1/version —— 本组件把两者并列展示，并在
 * 双方 commit 均已知且不一致时给出醒目错配提示。任一侧未知（本地 dev）
 * 则安静展示「未注入」，绝不猜测。 */

import { useQuery } from '@tanstack/react-query'
import { TriangleAlert } from 'lucide-react'
import { getApiVersion } from '../../api/client'
import { cx } from '../ui/cx'

const WEB_COMMIT = (import.meta.env.VITE_GIT_COMMIT ?? '').trim()

function short(commit: string): string {
  return commit.slice(0, 7)
}

export function AboutVersion() {
  const { data } = useQuery({
    queryKey: ['api-version'],
    queryFn: ({ signal }) => getApiVersion(signal),
    staleTime: 60_000,
  })

  const bffCommit = (data?.commit ?? '').trim()
  const mismatch =
    WEB_COMMIT !== '' && bffCommit !== '' && WEB_COMMIT !== bffCommit

  return (
    <div className="mt-4">
      <dl className="divide-y divide-[var(--lumi-separator)] text-sm">
        <div className="flex items-center justify-between py-2.5">
          <dt className="text-[var(--lumi-text-secondary)]">前端构建</dt>
          <dd className="font-mono text-xs text-[var(--lumi-text-primary)]">
            {WEB_COMMIT === '' ? '开发模式' : short(WEB_COMMIT)}
          </dd>
        </div>
        <div className="flex items-center justify-between py-2.5">
          <dt className="text-[var(--lumi-text-secondary)]">服务端 (BFF)</dt>
          <dd className="font-mono text-xs text-[var(--lumi-text-primary)]">
            {bffCommit === '' ? '未注入' : short(bffCommit)}
          </dd>
        </div>
      </dl>
      {mismatch && (
        <p
          role="status"
          className={cx(
            'mt-3 flex items-start gap-2 rounded-[var(--lumi-radius-md)]',
            'border border-[var(--lumi-warning-border,var(--lumi-border))]',
            'bg-[var(--lumi-surface)] px-3 py-2 text-xs leading-relaxed',
            'text-[var(--lumi-text-primary)]',
          )}
        >
          <TriangleAlert aria-hidden className="mt-0.5 size-3.5 shrink-0" />
          <span>
            前端与服务端构建不一致：请重建并重启 BFF 容器
            （docker compose -f docker-compose.prod.yml up -d --build），
            否则接口行为可能与界面不匹配。
          </span>
        </p>
      )}
    </div>
  )
}
