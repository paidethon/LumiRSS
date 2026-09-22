/**
 * O189：Conventional Commits 1.0.0 本地与 CI 共用的提交主题规范。
 * scope 对应真实业务域（web / bff / docs / ci / repo…）；
 * 历史遗留提交不在本检查范围（只校验增量提交）。
 */
export default {
  extends: ['@commitlint/config-conventional'],
  rules: {
    // 仓库历史的既有惯例：英文小写主题为主，允许中文描述（历史一致），
    // 这里只强制结构性规则，不强制语言。
    'subject-case': [0],
    'scope-case': [0],
    'body-max-line-length': [0],
  },
}
