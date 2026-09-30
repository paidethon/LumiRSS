/** keyboard-reading-mode — NEW-352 外接键盘阅读模式（会话级，纯逻辑核心）。
 *
 * 连接外接键盘时展示当前页面可执行的命令，用户可**暂时启用**并测试：
 * - 「暂时」= sessionStorage（关标签页即失效，绝不写入便携设置）；
 * - 命令目录来自既有 effectiveShortcuts（全局动作，含用户自定义重绑）
 *   与 reader-keynav 的固定文章域键位——不复制第二份目录；
 * - **不覆盖系统快捷键**：匹配纯函数对带修饰键（Ctrl/⌘/Alt）的组合
 *   一律返回 null（透传给系统/浏览器），与既有全局处理器的纪律一致；
 * - 探测（测试）只显示「会触发哪条命令」，绝不代为执行——避免训练期
 *   误操作真实数据。
 *
 * 键盘检测：`(any-pointer: fine)` / `(hover: hover) and (pointer: fine)`
 * 粗判；matchMedia 不可用 → null（诚实「无法判定」，不假装检测到）。 */

export const KB_READING_SESSION_KEY = 'lumirss-kb-reading-mode'

/** 读取会话启用状态（缺失/损坏 → false；临时语义默认关）。 */
export function readKbReadingSession(
  storage: Storage | null = typeof sessionStorage === 'undefined' ? null : sessionStorage,
): boolean {
  if (storage === null) return false
  try {
    return storage.getItem(KB_READING_SESSION_KEY) === '1'
  } catch {
    return false
  }
}

/** 写入会话启用状态（写失败静默：会话级增强）。 */
export function writeKbReadingSession(
  enabled: boolean,
  storage: Storage | null = typeof sessionStorage === 'undefined' ? null : sessionStorage,
): void {
  if (storage === null) return
  try {
    if (enabled) storage.setItem(KB_READING_SESSION_KEY, '1')
    else storage.removeItem(KB_READING_SESSION_KEY)
  } catch {
    // 隐私模式拒绝写入：会话开关尽力而为。
  }
}

/** 物理键盘粗判。返回 true / false；环境不支持 matchMedia → null（无法判定）。 */
export function hasPhysicalKeyboard(
  mq: ((query: string) => { matches: boolean } | null) | null = typeof window === 'undefined'
    ? null
    : (query: string) => window.matchMedia(query),
): boolean | null {
  if (mq === null) return null
  try {
    const fine = mq('(any-pointer: fine)')
    if (fine !== null && fine.matches) return true
    const hoverFine = mq('(hover: hover) and (pointer: fine)')
    if (hoverFine !== null && hoverFine.matches) return true
    return false
  } catch {
    return null
  }
}

/** 面板页面上下午：列表页 / 阅读页（选中文章 = 阅读页）。 */
export type KbReadingPage = 'list' | 'reader'

export interface KbReadingCommand {
  id: string
  keys: string
  action: string
  /** 用户自定义重绑时如实标注。 */
  overridden: boolean
}

/** 全局动作参与探测的「裸键」默认表（与 SHORTCUT_ACTIONS 默认绑定一致；
 * commandPalette 是修饰键组合——系统快捷键，永不参与探测）。
 * 动作标签与 SHORTCUT_ACTIONS 同源拷入时会漂移，因此只存 id→标签的
 * 最小映射（帮助弹窗/设置页仍是唯一展示事实源，本表仅探测面板用）。 */
const PLAIN_KEY_DEFAULTS: Record<string, readonly string[]> = {
  next: ['j', 'ArrowDown'],
  prev: ['k', 'ArrowUp'],
  toggleUnread: ['u'],
  toggleStar: ['s'],
  search: ['/'],
  help: ['?'],
  closeOverlay: ['Escape'],
}

export /** 探测面板专用文案——与快捷键速查表（SHORTCUTS）刻意措辞不同，
 * 两表同页渲染时不产生重复文本（gate-b 基线）。 */
const ACTION_LABELS: Record<string, string> = {
  next: '选中下一篇',
  prev: '选中上一篇',
  toggleUnread: '未读视图开关',
  toggleStar: '收藏当前文章',
  search: '跳到搜索页',
  help: '打开快捷键帮助',
  closeOverlay: '关闭最上层弹层',
}

/** 解析用户自定义绑定串为裸键（仅无修饰键组合参与；带修饰键 → null）。
 * 自定义绑定格式为 normalizeCombo 产物（如 'shift+?'）。 */
export function customPlainKey(combo: string): string | null {
  const parts = combo.split('+').map((part) => part.trim().toLowerCase())
  if (parts.some((part) => part === 'ctrl' || part === 'meta' || part === 'alt' || part === 'mod')) {
    return null
  }
  const key = parts[parts.length - 1]
  return key !== undefined && key !== '' ? key : null
}

/** 当前页面可执行命令目录（含自定义重绑的生效键位）。
 * 阅读页额外附文章域固定键位（不参与探测，展示 only）。 */
export function kbReadingCommands(
  custom: Record<string, string>,
  page: KbReadingPage,
): { probe: KbReadingCommand[]; readerOnly: KbReadingCommand[] } {
  const probe: KbReadingCommand[] = Object.entries(PLAIN_KEY_DEFAULTS).map(([id, plainKeys]) => {
    const customCombo = custom[id]
    const hasCustom = typeof customCombo === 'string' && customCombo !== ''
    const effectiveKey = hasCustom ? customPlainKey(customCombo ?? '') : null
    return {
      id,
      keys:
        effectiveKey !== null
          ? effectiveKey
          : hasCustom
            ? (customCombo ?? '')
            : (plainKeys.join(' / ') ?? ''),
      action: ACTION_LABELS[id] ?? id,
      overridden: hasCustom,
    }
  })
  const readerOnly: KbReadingCommand[] =
    page === 'reader'
      ? [
          { id: 'keynav-down', keys: 'Alt+↓', action: '纯键盘定位：下一个目标', overridden: false },
          { id: 'keynav-up', keys: 'Alt+↑', action: '纯键盘定位：上一个目标', overridden: false },
        ]
      : []
  return { probe, readerOnly }
}

/** 探测匹配（纯函数）：按键事件 → 命中动作 id 或 null。
 * 纪律（测试钉定）：带修饰键（Ctrl/⌘/Alt）一律 null（不覆盖系统快捷键）；
 * IME 组合中（isComposing / keyCode 229）一律 null。自定义重绑参与匹配。 */
export function matchKeyboardProbe(
  input: {
    key: string
    ctrlKey?: boolean
    metaKey?: boolean
    altKey?: boolean
    isComposing?: boolean | null
    keyCode?: number | null
  },
  custom: Record<string, string>,
): string | null {
  if (
    input.ctrlKey === true ||
    input.metaKey === true ||
    input.altKey === true ||
    input.isComposing === true ||
    input.keyCode === 229
  ) {
    return null
  }
  const pressed = input.key.toLowerCase()
  for (const [id, plainKeys] of Object.entries(PLAIN_KEY_DEFAULTS)) {
    const customCombo = custom[id]
    const effective =
      typeof customCombo === 'string' && customCombo !== ''
        ? customPlainKey(customCombo)
        : null
    const keys = effective !== null ? [effective] : plainKeys
    if (keys.some((candidate) => candidate.toLowerCase() === pressed)) return id
  }
  return null
}
