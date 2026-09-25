/** LocalTranslationCapabilitySection — 设置 → 翻译 的「本机翻译能力」区。
 *
 * N089 离线能力检测：按钮触发一次 REAL 探测（绝不伪造离线）——
 * (a) 系统框架：Chrome Translator API 存在 + 语言对支持（既有探测）；
 * (b) 浏览器模型：固定短句的真实内置翻译推理；
 * (c) 云端（需网络）：已配置 AI 端点的一次有界可达性探测。
 * 结果按层标注（系统框架 / 浏览器模型 / 云端），并给出「离线可用」
 * 标记——仅当 (b) 真实成功且 (c) 探测失败（云端不可达时的实际证据）。
 *
 * N088 翻译模型存储管理：语言对能力网格（支持/可下载/不支持，逐对
 * 如实），存储大小诚实标注「浏览器托管，无法精确计量」（不编造
 * MB 数字）；「清除本机翻译模型」按浏览器 API 实际能力呈现——接口
 * 不存在时诚实给出「无清除接口 + 浏览器设置指引」。 */

import { useState } from 'react'
import { Loader2, RefreshCw, Trash2 } from 'lucide-react'
import {
  localTranslatorPairStatus,
  translatorModelDeletionAvailable,
  deleteLocalTranslatorModels,
  type LocalTranslatorAvailability,
} from '../../lib/local-translator'
import {
  runOfflineTranslationProbe,
  type OfflineProbeResult,
} from '../../lib/offline-translation-probe'
import { Button } from '../ui/Button'
import { cx } from '../ui/cx'

/** 网格展示的语言对（本机翻译的现实目标：中英互译）。 */
const CAPABILITY_PAIRS: [sourceLanguage: string, targetLanguage: string][] = [
  ['en', 'zh'],
  ['zh', 'en'],
]

const AVAILABILITY_LABELS: Record<LocalTranslatorAvailability, string> = {
  available: '支持',
  downloadable: '可下载（未就绪）',
  downloading: '下载中',
  unavailable: '不支持',
  unsupported: '浏览器不支持',
}

const AVAILABILITY_TONE: Record<LocalTranslatorAvailability, string> = {
  available: 'text-[var(--lumi-accent-text)]',
  downloadable: 'text-[var(--lumi-text-secondary)]',
  downloading: 'text-[var(--lumi-text-secondary)]',
  unavailable: 'text-[var(--lumi-text-tertiary)]',
  unsupported: 'text-[var(--lumi-text-tertiary)]',
}

export function LocalTranslationCapabilitySection({
  remoteEndpoint,
}: {
  /** 已配置的云端 AI 端点（AI 设置 baseUrl；空 = 未配置）。 */
  remoteEndpoint: string
}) {
  // ---- N089：离线能力检测 ----
  const [probe, setProbe] = useState<OfflineProbeResult | null>(null)
  const [probeBusy, setProbeBusy] = useState(false)
  const [probeError, setProbeError] = useState<string | null>(null)
  const runProbe = () => {
    setProbeBusy(true)
    setProbeError(null)
    runOfflineTranslationProbe({
      sourceLanguage: 'en',
      targetLanguage: 'zh',
      remoteEndpoint: remoteEndpoint !== '' ? remoteEndpoint : null,
    })
      .then((result) => setProbe(result))
      .catch(() => setProbeError('检测失败，请稍后重试。'))
      .finally(() => setProbeBusy(false))
  }

  // ---- N088：语言对能力网格 + 存储管理 ----
  const [pairs, setPairs] = useState<
    { source: string; target: string; state: LocalTranslatorAvailability }[]
    | null
  >(null)
  const [gridBusy, setGridBusy] = useState(false)
  const loadGrid = () => {
    setGridBusy(true)
    void Promise.all(
      CAPABILITY_PAIRS.map(async ([source, target]) => ({
        source,
        target,
        state: await localTranslatorPairStatus(source, target),
      })),
    )
      .then(setPairs)
      .finally(() => setGridBusy(false))
  }
  const [deleting, setDeleting] = useState(false)
  const [deleteNote, setDeleteNote] = useState<string | null>(null)
  const deletionSupported = translatorModelDeletionAvailable()
  const clearModels = () => {
    setDeleting(true)
    void deleteLocalTranslatorModels()
      .then((deleted) => {
        setDeleteNote(
          deleted
            ? '已请求浏览器清除本机翻译模型（下次使用对应语言对时会重新下载）。'
            : '清除失败：浏览器拒绝了清除请求。',
        )
      })
      .finally(() => setDeleting(false))
  }

  return (
    <section
      data-lumi-local-translation-capability=""
      className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-3.5"
    >
      <h3 className="text-sm font-medium text-[var(--lumi-text-primary)]">
        本机翻译能力（此设备）
      </h3>
      <p className="mt-2 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
        检测结果只代表「此设备、此刻」的真实能力；检测绝不伪造离线，也绝不外发文章内容——探测只包含语言对支持查询、一条固定短句的浏览器推理与一次端点可达性探测。
      </p>

      {/* N089：离线能力检测 */}
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Button
          size="sm"
          variant="secondary"
          disabled={probeBusy}
          onClick={runProbe}
        >
          {probeBusy ? (
            <Loader2 aria-hidden className="size-3.5 animate-spin" />
          ) : (
            <RefreshCw aria-hidden className="size-3.5" />
          )}
          离线能力检测
        </Button>
        {probe !== null && probe.offlineAvailable && (
          <span
            data-lumi-offline-available=""
            className="rounded-[var(--lumi-radius-sm)] bg-[var(--lumi-accent-soft)] px-1.5 py-0.5 text-xs text-[var(--lumi-accent-text)]"
          >
            离线可用
          </span>
        )}
      </div>
      {probeError !== null && (
        <p role="alert" className="mt-1 text-xs text-[var(--lumi-danger)]">
          {probeError}
        </p>
      )}
      {probe !== null && (
        <dl
          data-lumi-offline-probe-result=""
          className="mt-2 flex flex-col gap-1 text-xs"
        >
          <ProbeRow
            label="系统框架"
            ok={probe.system.ok}
            detail={probe.system.detail}
          />
          <ProbeRow
            label="浏览器模型"
            ok={probe.browser.ok}
            detail={probe.browser.detail}
          />
          <ProbeRow
            label="云端（需网络）"
            ok={probe.cloud.ok}
            detail={probe.cloud.detail}
          />
          <li className="text-[var(--lumi-text-tertiary)]">
            「离线可用」仅在浏览器模型实测成功、且云端端点探测失败时给出。
          </li>
        </dl>
      )}

      {/* N088：语言对能力网格 + 存储（诚实：浏览器托管，无法精确计量） */}
      <div className="mt-4 flex flex-wrap items-center gap-2">
        <Button
          size="sm"
          variant="secondary"
          disabled={gridBusy}
          onClick={loadGrid}
        >
          {gridBusy ? <Loader2 aria-hidden className="size-3.5 animate-spin" /> : null}
          检测语言对支持
        </Button>
      </div>
      {pairs !== null && (
        <table className="mt-2 w-full text-xs" data-lumi-model-grid="">
          <caption className="sr-only">本机翻译语言对支持情况</caption>
          <thead>
            <tr className="text-left text-[var(--lumi-text-tertiary)]">
              <th scope="col" className="py-1 pr-2 font-normal">语言对</th>
              <th scope="col" className="py-1 font-normal">支持情况</th>
            </tr>
          </thead>
          <tbody>
            {pairs.map((pair) => (
              <tr key={`${pair.source}>${pair.target}`}>
                <td className="py-1 pr-2 text-[var(--lumi-text-secondary)]">
                  {pair.source} → {pair.target}
                </td>
                <td className={cx('py-1', AVAILABILITY_TONE[pair.state])}>
                  {AVAILABILITY_LABELS[pair.state]}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <p className="mt-2 text-xs leading-relaxed text-[var(--lumi-text-tertiary)]">
        模型存储由浏览器托管，无法精确计量（Lumi 不编造大小数字）；以上为逐语言对的真实可用性。
      </p>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <Button
          size="sm"
          variant="secondary"
          disabled={deleting || !deletionSupported}
          title={
            deletionSupported
              ? '请求浏览器清除本机已下载的翻译语言包'
              : '此浏览器没有提供清除本机翻译模型的接口'
          }
          onClick={clearModels}
        >
          {deleting ? <Loader2 aria-hidden className="size-3.5 animate-spin" /> : <Trash2 aria-hidden className="size-3.5" />}
          清除本机翻译模型
        </Button>
        {!deletionSupported && (
          <span className="text-xs text-[var(--lumi-text-tertiary)]">
            无清除接口：可在浏览器「设置 → 隐私和安全 → 清除浏览数据」（勾选Cookie 及其他网站数据）删除下载的语言包。
          </span>
        )}
      </div>
      {deleteNote !== null && (
        <p role="status" className="mt-1 text-xs text-[var(--lumi-text-secondary)]">
          {deleteNote}
        </p>
      )}
    </section>
  )
}

function ProbeRow({
  label,
  ok,
  detail,
}: {
  label: string
  ok: boolean | null
  detail: string
}) {
  return (
    <div className="flex items-start gap-2">
      <dt className="w-24 shrink-0 text-[var(--lumi-text-secondary)]">{label}</dt>
      <dd>
        <span
          className={cx(
            'font-medium',
            ok === true
              ? 'text-[var(--lumi-accent-text)]'
              : ok === false
                ? 'text-[var(--lumi-danger)]'
                : 'text-[var(--lumi-text-tertiary)]',
          )}
        >
          {ok === true ? '可用' : ok === false ? '不可用' : '未配置'}
        </span>
        <span className="ml-1 text-[var(--lumi-text-tertiary)]">{detail}</span>
      </dd>
    </div>
  )
}
