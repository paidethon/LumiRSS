/** 语义 class 组合工具 — 0009 Gate 1。
 *
 * 极简 clsx 替代（项目零依赖原则）：过滤 falsy、拼接。
 * primitives 内部使用；业务组件不直接依赖。 */

export function cx(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(' ')
}
