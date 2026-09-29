/** NEW-264 翻译服务能力比较 — 用户自选的少量非敏感样本（1..5 段、每段
 * ≤500 字符）对已配置服务做显式对照：逐侧逐样本结果/耗时/错误。
 * 绝不自动发送整库；零缓存写入；无已配置服务时诚实 unavailable。 */

import { useMutation, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import {
  listCapabilityProbes,
  runCapabilityProbe,
  type CapabilityProbeReport,
} from '../../api/new261'
import { Button } from '../ui/Button'
import { NoticeLine } from './parts'

const SAMPLE_MAX = 500
const SAMPLE_MAX_COUNT = 5

export function CapabilityProbePanel() {
  const historyQuery = useQuery({
    queryKey: ['new264-capability-probes'],
    queryFn: ({ signal }) => listCapabilityProbes(signal),
  })
  const [samples, setSamples] = useState<string[]>([''])
  const [report, setReport] = useState<CapabilityProbeReport | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const probeMutation = useMutation({
    mutationFn: () => runCapabilityProbe(samples.map((sample) => sample.trim()).filter((sample) => sample !== '')),
    onSuccess: (result) => {
      setReport(result)
      setNotice(result.available ? null : `本轮对照不可用：${result.reason}`)
    },
    onError: (error) => setNotice(error instanceof Error ? error.message : '探测失败'),
  })

  const filled = samples.map((sample) => sample.trim()).filter((sample) => sample !== '')

  return (
    <div className="flex flex-col gap-2">
      <p className="text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
        只比较你自己填入的样本（≤5 段、每段 ≤500 字符），不会发送整库；结果不写入翻译缓存。
      </p>
      {samples.map((sample, index) => (
        <textarea
          key={index}
          value={sample}
          maxLength={SAMPLE_MAX}
          rows={2}
          onChange={(event) =>
            setSamples((prev) => prev.map((item, i) => (i === index ? event.target.value : item)))
          }
          aria-label={`样本 ${index + 1}`}
          placeholder={`样本 ${index + 1}（非敏感短句）`}
          className="w-full rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] bg-[var(--lumi-surface)] px-2 py-1 text-xs leading-relaxed"
        />
      ))}
      <div className="flex flex-wrap items-center gap-2">
        <Button
          size="sm"
          variant="ghost"
          disabled={samples.length >= SAMPLE_MAX_COUNT}
          onClick={() => setSamples((prev) => [...prev, ''])}
        >
          加一段样本
        </Button>
        <Button
          size="sm"
          variant="secondary"
          disabled={filled.length === 0 || probeMutation.isPending}
          onClick={() => probeMutation.mutate()}
        >
          运行对照（{filled.length} 段）
        </Button>
      </div>

      {report !== null && (
        <div className="flex flex-col gap-2" aria-label="能力对照结果">
          {Object.entries(report.sides).map(([sideName, side]) => (
            <div key={sideName} className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-2 text-xs">
              <p className="font-medium text-[var(--lumi-text-primary)]">
                {sideName === 'ai' ? 'AI 翻译' : sideName === 'libretranslate' ? 'LibreTranslate' : sideName}
                {!side.configured && <span className="ml-2 text-[var(--lumi-text-tertiary)]">未配置 · {side.reason}</span>}
              </p>
              {side.configured && side.samples !== undefined && (
                <ul className="mt-1 flex flex-col gap-1 text-[var(--lumi-text-secondary)]">
                  {side.samples.map((outcome) => (
                    <li key={outcome.index} className="leading-relaxed">
                      样本 {outcome.index + 1}：
                      {outcome.ok ? (
                        <span>
                          完成 · {outcome.elapsedMs} ms ·「{(outcome.text ?? '').slice(0, 60)}」
                        </span>
                      ) : (
                        <span className="text-[var(--lumi-danger)]">失败（{outcome.error}）· {outcome.elapsedMs} ms</span>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ))}
        </div>
      )}

      {historyQuery.data && historyQuery.data.probes.length > 0 && (
        <p className="text-xs text-[var(--lumi-text-tertiary)]">
          历史报告 {historyQuery.data.probes.length} 份（最近：{historyQuery.data.probes[0]?.createdAt}）。
        </p>
      )}
      {notice !== null && <NoticeLine tone={notice.includes('不可用') || notice.includes('失败') ? 'error' : 'info'}>{notice}</NoticeLine>}
    </div>
  )
}
