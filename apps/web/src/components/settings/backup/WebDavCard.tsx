/** WebDavCard — 0018 G8：服务器端 WebDAV 备份目标设置。
 *
 * password 写只读：表单只在用户输入新值时提交 password；界面只显示
 * passwordConfigured 状态，永不回显（GET 响应本身也不含密码）。
 * 保存与「测试连接」分离；测试结果如实展示成功/失败与脱敏原因。
 */

import { useEffect, useState } from 'react'
import { useTestWebDavMutation, useUpdateWebDavSettingsMutation, useWebDavSettings } from '../../../api/queries'
import { Button } from '../../ui/Button'
import { Skeleton } from '../../ui/Skeleton'
import { Switch } from '../../ui/Switch'
import { cx } from '../../ui/cx'
import { AlertCircle, CheckCircle2, CloudUpload, Loader2 } from 'lucide-react'

const inputClass = cx(
  'w-full min-h-9 rounded-[var(--lumi-radius-lg)] border border-[var(--lumi-border)]',
  'bg-[var(--lumi-surface)] px-2.5 text-sm text-[var(--lumi-text-primary)]',
  'focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[var(--lumi-focus-ring)]',
)

export function WebDavCard() {
  const settings = useWebDavSettings()
  const save = useUpdateWebDavSettingsMutation()
  const test = useTestWebDavMutation()

  const [serverUrl, setServerUrl] = useState('')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [remoteDir, setRemoteDir] = useState('')
  const [tlsVerify, setTlsVerify] = useState(true)
  const [savedNote, setSavedNote] = useState<string | null>(null)

  // 服务端值到达后同步一次表单（仅当用户未开始编辑时覆盖，避免打断输入：
  // 用「初始为空」作为未编辑信号——简单且对单用户设置页足够）。
  useEffect(() => {
    const doc = settings.data
    if (!doc) return
    setServerUrl((prev) => prev || doc.serverUrl)
    setUsername((prev) => prev || doc.username)
    setRemoteDir((prev) => prev || doc.remoteDir)
    setTlsVerify(doc.tlsVerify)
  }, [settings.data])

  const dirty =
    settings.data !== undefined &&
    (serverUrl !== settings.data.serverUrl ||
      username !== settings.data.username ||
      remoteDir !== settings.data.remoteDir ||
      tlsVerify !== settings.data.tlsVerify ||
      password.trim() !== '')

  const doSave = () => {
    setSavedNote(null)
    save.mutate(
      {
        serverUrl: serverUrl.trim(),
        username: username.trim(),
        remoteDir: remoteDir.trim(),
        tlsVerify,
        // 只有输入了新值才提交密码字段（写只读；空 = 不修改）
        ...(password.trim() ? { password } : {}),
      },
      {
        onSuccess: () => {
          setPassword('')
          setSavedNote('已保存。')
        },
      },
    )
  }

  if (settings.isError) {
    return (
      <p role="alert" className="flex items-start gap-1.5 text-sm text-[var(--lumi-danger)]">
        <AlertCircle aria-hidden className="mt-0.5 size-4 shrink-0" />
        无法获取 WebDAV 设置：{settings.error instanceof Error ? settings.error.message : '请稍后重试。'}
      </p>
    )
  }

  return (
    <div className="rounded-[var(--lumi-radius-md)] border border-[var(--lumi-border)] p-3.5">
      <div className="flex items-center gap-2">
        <CloudUpload aria-hidden className="size-4 shrink-0 text-[var(--lumi-text-tertiary)]" />
        <h3 className="text-sm font-medium text-[var(--lumi-text-primary)]">WebDAV 远程备份</h3>
        {settings.data?.configured && (
          <span className="ml-auto rounded-[var(--lumi-radius-full)] bg-[var(--lumi-surface-selected)] px-2 py-0.5 text-[11px] text-[var(--lumi-text-tertiary)]">
            已配置
          </span>
        )}
      </div>
      <p className="mt-1 text-xs leading-relaxed text-[var(--lumi-text-secondary)]">
        备份经服务器端上传到你的 WebDAV 网盘（浏览器不直连）。密码只写入服务器，保存后不可回读。
      </p>

      {settings.data === undefined ? (
        <div className="mt-3 flex flex-col gap-2" aria-label="正在加载 WebDAV 设置">
          <Skeleton className="h-9 w-full" />
          <Skeleton className="h-9 w-full" />
        </div>
      ) : (
        <div className="mt-3 grid gap-3">
          <label className="grid gap-1.5">
            <span className="text-xs text-[var(--lumi-text-secondary)]">服务地址（https）</span>
            <input
              type="url"
              inputMode="url"
              autoComplete="off"
              value={serverUrl}
              onChange={(e) => setServerUrl(e.target.value)}
              placeholder="https://dav.example.com/dav/"
              className={inputClass}
            />
          </label>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="grid gap-1.5">
              <span className="text-xs text-[var(--lumi-text-secondary)]">用户名</span>
              <input
                type="text"
                autoComplete="off"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                className={inputClass}
              />
            </label>
            <label className="grid gap-1.5">
              <span className="text-xs text-[var(--lumi-text-secondary)]">
                密码{settings.data.passwordConfigured ? '（已保存；留空保持不变）' : ''}
              </span>
              <input
                type="password"
                autoComplete="new-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder={settings.data.passwordConfigured ? '••••••••' : ''}
                className={inputClass}
              />
            </label>
          </div>
          <label className="grid gap-1.5">
            <span className="text-xs text-[var(--lumi-text-secondary)]">远程目录（可选）</span>
            <input
              type="text"
              autoComplete="off"
              value={remoteDir}
              onChange={(e) => setRemoteDir(e.target.value)}
              placeholder="LumiRSS"
              className={inputClass}
            />
          </label>
          <div className="flex items-center justify-between gap-3">
            <div className="min-w-0">
              <p className="text-sm text-[var(--lumi-text-primary)]">校验 TLS 证书</p>
              <p className="mt-0.5 text-xs leading-relaxed text-[var(--lumi-text-tertiary)]">
                自签名证书的私有部署可关闭（仅建议受信网络）。
              </p>
            </div>
            <Switch
              checked={tlsVerify}
              onCheckedChange={setTlsVerify}
              label={tlsVerify ? 'TLS 校验开启' : 'TLS 校验关闭'}
            />
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <Button size="sm" onClick={doSave} disabled={save.isPending || !dirty}>
              {save.isPending ? <Loader2 aria-hidden className="size-3.5 animate-spin" /> : <CheckCircle2 aria-hidden className="size-3.5" />}
              保存
            </Button>
            <Button
              size="sm"
              variant="secondary"
              onClick={() => { setSavedNote(null); test.mutate() }}
              disabled={test.isPending || !settings.data.configured}
            >
              {test.isPending ? <Loader2 aria-hidden className="size-3.5 animate-spin" /> : null}
              测试连接
            </Button>
            {savedNote && (
              <span role="status" className="text-xs text-[var(--lumi-accent)]">{savedNote}</span>
            )}
          </div>

          {save.isError && (
            <p role="alert" className="text-xs leading-relaxed text-[var(--lumi-danger)]">
              保存失败：{save.error instanceof Error ? save.error.message : '请稍后重试。'}
            </p>
          )}
          {test.isError && (
            <p role="alert" className="text-xs leading-relaxed text-[var(--lumi-danger)]">
              测试失败：{test.error instanceof Error ? test.error.message : '请稍后重试。'}
            </p>
          )}
          {test.data && (
            <p
              role="status"
              className={cx(
                'text-xs leading-relaxed',
                test.data.status === 'ok' ? 'text-[var(--lumi-accent)]' : 'text-[var(--lumi-danger)]',
              )}
            >
              {test.data.status === 'ok' ? '连接成功。' : `连接失败：${test.data.message ?? '未知原因'}`}
            </p>
          )}
        </div>
      )}
    </div>
  )
}
