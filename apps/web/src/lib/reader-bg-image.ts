/** reader-bg-image — 阅读背景图片纯逻辑（P14）。
 *
 * 设备本地、隐私优先的背景图片管线：
 * - 文件输入 → canvas 降采样（最长宽 2560px）→ JPEG data URL；
 * - 严格上限：编码后 data URL ≤ 2MB（超限先降质量再降分辨率，
 *   仍超限则诚实拒绝，绝不静默放宽）；
 * - 可读性检查：全图平均相对亮度（WCAG sRGB→linear）→
 *   建议遮罩不透明度 + 中文提示（背景较亮/较暗，已建议遮罩 X%）；
 * - 全程零网络：不做任何 fetch / XHR / 上传（有测试断言钉死）。
 *
 * 存储侧：data URL 由调用方写入 settings 键 readerBackgroundImage
 * （设备本地，绝不进 PORTABLE_KEYS）；归一化校验复用本模块的
 * isValidBgImageDataUrl。 */

/** 编码后 data URL 的严格字符上限（base64 为 ASCII，字符数≈字节数）。 */
export const BG_IMAGE_MAX_BYTES = 2 * 1024 * 1024
/** 降采样后的最大宽度（px，等比缩放）。 */
export const BG_IMAGE_MAX_WIDTH = 2560
/** 遮罩不透明度边界与默认值（%，0–80）。 */
export const BG_IMAGE_OVERLAY_MIN = 0
export const BG_IMAGE_OVERLAY_MAX = 80
export const BG_IMAGE_OVERLAY_DEFAULT = 40

/** 质量递减序列：先降 JPEG 质量，仍超限再降分辨率重试（有界）。 */
const ENCODE_QUALITIES = [0.85, 0.7, 0.55] as const
const ENCODE_MAX_ROUNDS = 2

/** 允许的 data URL 形态：仅位图 MIME + base64，且长度不超过上限。 */
const BG_IMAGE_DATA_URL_RE = /^data:image\/(?:png|jpeg|jpg|webp);base64,[A-Za-z0-9+/=]+$/

/** settings 归一化用：仅接受带位图 MIME 的 base64 data URL 且 ≤ 上限。 */
export function isValidBgImageDataUrl(value: unknown): value is string {
  return (
    typeof value === 'string' &&
    value.length <= BG_IMAGE_MAX_BYTES &&
    BG_IMAGE_DATA_URL_RE.test(value)
  )
}

/** 遮罩不透明度归一化：数值钳制到 [0, 80] 并取整；非法值回默认 40。 */
export function normalizeOverlayOpacity(value: unknown): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) return BG_IMAGE_OVERLAY_DEFAULT
  return Math.round(Math.min(BG_IMAGE_OVERLAY_MAX, Math.max(BG_IMAGE_OVERLAY_MIN, value)))
}

/** 单像素 sRGB → WCAG 相对亮度（与 reader-style.relativeLuminance 同算法，
 * 本模块保持零依赖故内联一份）。 */
function pixelLuminance(r: number, g: number, b: number): number {
  const [lr, lg, lb] = [r, g, b].map((v) => {
    const c = v / 255
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
  })
  return 0.2126 * lr + 0.7152 * lg + 0.0722 * lb
}

/** RGBA 像素数组的平均相对亮度：均匀采样 ≤4096 像素控制成本
 * （2560×1440 全量 ≈ 370 万像素，采样对「平均明暗」足够稳定）。 */
export function averageImageLuminance(pixels: ArrayLike<number>): number {
  const pixelCount = Math.floor(pixels.length / 4)
  if (pixelCount === 0) return 1
  const pixelStride = Math.max(1, Math.floor(pixelCount / 4096))
  const byteStride = pixelStride * 4
  let total = 0
  let sampled = 0
  for (let i = 0; i + 3 < pixels.length; i += byteStride) {
    total += pixelLuminance(pixels[i], pixels[i + 1], pixels[i + 2])
    sampled++
  }
  return sampled === 0 ? 1 : total / sampled
}

/** 可读性检查的「明暗适中」亮度带（WCAG 线性亮度）：
 * 感知中间调（sRGB ~128 的灰）的线性亮度 ≈ 0.21，因此带宽取
 * [0.1, 0.4]——带内视为适中（默认遮罩），带外按偏离程度加强遮罩。 */
const BALANCED_LUMINANCE_LOW = 0.1
const BALANCED_LUMINANCE_HIGH = 0.4

/** 亮度 → 建议遮罩（%）：「明暗适中」带内保持默认 40%；越偏亮/偏暗
 * 遮罩越强（线性斜坡），极值 80%，保证文字始终由背景色调色板主导。 */
export function recommendOverlayOpacity(luminance: number): number {
  const clamped = Math.min(1, Math.max(0, luminance))
  const excess =
    clamped > BALANCED_LUMINANCE_HIGH
      ? (clamped - BALANCED_LUMINANCE_HIGH) / (1 - BALANCED_LUMINANCE_HIGH)
      : clamped < BALANCED_LUMINANCE_LOW
        ? (BALANCED_LUMINANCE_LOW - clamped) / BALANCED_LUMINANCE_LOW
        : 0
  return normalizeOverlayOpacity(
    BG_IMAGE_OVERLAY_DEFAULT + excess * (BG_IMAGE_OVERLAY_MAX - BG_IMAGE_OVERLAY_DEFAULT),
  )
}

export interface BgImageHint {
  tone: 'bright' | 'dark' | 'balanced'
  text: string
}

/** 可读性提示文案（需求原文格式：背景较亮/较暗，已建议遮罩 X%）。 */
export function bgImageHint(luminance: number): BgImageHint {
  const overlay = recommendOverlayOpacity(luminance)
  if (luminance > BALANCED_LUMINANCE_HIGH) {
    return { tone: 'bright', text: `背景较亮，已建议遮罩 ${overlay}%` }
  }
  if (luminance < BALANCED_LUMINANCE_LOW) {
    return { tone: 'dark', text: `背景较暗，已建议遮罩 ${overlay}%` }
  }
  return { tone: 'balanced', text: `背景明暗适中，已按遮罩 ${overlay}% 处理` }
}

export interface BgImageProcessSuccess {
  ok: true
  /** 重编码后的 JPEG data URL（≤ BG_IMAGE_MAX_BYTES）。 */
  dataUrl: string
  width: number
  height: number
  /** 全图平均相对亮度（0–1）。 */
  luminance: number
  /** 建议遮罩不透明度（%，0–80）。 */
  recommendedOverlay: number
  hint: BgImageHint
}

export type BgImageProcessResult = BgImageProcessSuccess | { ok: false; error: string }

/** FileReader → data URL（统一错误文案）。 */
function readFileAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result))
    reader.onerror = () => reject(new Error('读取图片文件失败。'))
    reader.readAsDataURL(file)
  })
}

/** Image 解码（onload/onerror 二态；不关心尺寸前的自然宽高之外信息）。 */
function decodeImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image()
    image.onload = () => resolve(image)
    image.onerror = () => reject(new Error('图片无法解码，请换一张试试。'))
    image.src = src
  })
}

/** 画布编码循环：质量递减 × 一轮降分辨率重试，全部超限才拒绝。 */
function encodeWithinBudget(
  image: HTMLImageElement,
): BgImageProcessResult {
  const canvas = document.createElement('canvas')
  const ctx = canvas.getContext('2d')
  if (ctx === null) {
    return { ok: false, error: '当前浏览器不支持图片处理（Canvas 不可用）。' }
  }

  const naturalWidth = image.naturalWidth || image.width
  const naturalHeight = image.naturalHeight || image.height
  if (naturalWidth <= 0 || naturalHeight <= 0) {
    return { ok: false, error: '图片尺寸无效，请换一张试试。' }
  }

  let width = naturalWidth
  let height = naturalHeight

  const drawScaled = (w: number, h: number) => {
    canvas.width = w
    canvas.height = h
    ctx.drawImage(image, 0, 0, w, h)
    return ctx.getImageData(0, 0, w, h)
  }

  // 首轮：降采样到 ≤ BG_IMAGE_MAX_WIDTH（等比）。
  const initialScale = Math.min(1, BG_IMAGE_MAX_WIDTH / width)
  width = Math.max(1, Math.round(width * initialScale))
  height = Math.max(1, Math.round(height * initialScale))
  const imageData = drawScaled(width, height)
  const luminance = averageImageLuminance(imageData.data)
  const recommendedOverlay = recommendOverlayOpacity(luminance)
  const hint = bgImageHint(luminance)

  for (let round = 0; round < ENCODE_MAX_ROUNDS; round++) {
    for (const quality of ENCODE_QUALITIES) {
      const dataUrl = canvas.toDataURL('image/jpeg', quality)
      if (dataUrl.length <= BG_IMAGE_MAX_BYTES) {
        return { ok: true, dataUrl, width, height, luminance, recommendedOverlay, hint }
      }
    }
    // 仍超限：分辨率再降 30% 重试一轮（有界，最多两轮）。
    width = Math.max(1, Math.round(width * 0.7))
    height = Math.max(1, Math.round(height * 0.7))
    drawScaled(width, height)
  }

  return {
    ok: false,
    error: `图片编码后仍超过 2MB 上限，请换一张尺寸或内容更简单的图片。`,
  }
}

/** 完整管线：文件 → 校验 → 解码 → 降采样/亮度/建议 → 预算内编码。
 * 任何一步都不发起网络请求（隐私保证，测试钉死）。 */
export async function processBackgroundImageFile(file: File): Promise<BgImageProcessResult> {
  if (!/^image\//.test(file.type)) {
    return { ok: false, error: '仅支持图片文件（PNG / JPEG / WebP）。' }
  }
  try {
    const src = await readFileAsDataUrl(file)
    const image = await decodeImage(src)
    return encodeWithinBudget(image)
  } catch (error) {
    return {
      ok: false,
      error: error instanceof Error ? error.message : '图片处理失败，请重试。',
    }
  }
}
