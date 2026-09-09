# STATE.md — postmerge-reality-security-hardening

- 基线 SHA：`ad09bb2`（= origin/main，PR #36 已合并后的最新 main）
- 任务分支：`chore/postmerge-reality-security-hardening-20260908`（自 ad09bb2 创建）
- 执行时间：2026-09-09（长时间无人值守任务）
- 任务来源：post-merge 真实运行闭环 + Security & Operations Hardening（ROADMAP 0021 全部候选）

> 状态口径：所有「完成」均有 commit + 自动化测试 + 真实集成/浏览器验收证据
> 支撑，详见 [VALIDATION.md](VALIDATION.md)。

## 结果概览

| Phase | 内容 | 结果 |
|---|---|---|
| Gate 0 | 基线重建（BFF/Web/lint/build/drift/E2E） | 完成（2 个测试基础设施缺陷修复） |
| A1–A7 | 未验证项逐项关闭 | 完成（9 项 VERIFIED / 1 项平台外部阻塞 / 1 项 NOT APPLICABLE） |
| B | 0021 安全与运维候选逐项实施 | 完成（12 项，全部含回归测试） |
| C | 完整回归 + 真实集成 + 浏览器验收 | 完成（全绿，真实数字见 VALIDATION §1） |
| D | 对抗审查 + 文档同步 + push + PR | 见本文件下方状态 |

## 主要交付

- **真实备份闭环**：dev 栈 bind-mount 迁移 → fullBackupReady=true → 真实备份
  （78/78 校验和、密钥排除）→ 隔离实例恢复 → 重启核对 → 离线暂存校验。
- **Docker/代理根因闭环**：daemon systemd 代理指向不可达的 Windows 代理；
  等价构建路径验证 BFF/Web 镜像 + 生产栈全链路；daemon 修复留唯一 root 人工步骤。
- **真实 LibreTranslate**：v1.9.6 容器端到端（连接测试/批量翻译/错误路径/
  缓存零 provider/浏览器三模式），zh 兼容性结论成立。
- **Chrome Translator**：真机 Chrome 152 特征检测 + 诚实失败路径验证；
  Linux 不分发端上模型的证据链（chrome://components）。
- **0021 安全硬化**：翻译协议加固、有界锁池、服务级并发、回显上限、
  pydantic 端点、SecretValuePut 边界、内部 token（opt-in）、CSP/HSTS、
  全局请求体上限、控制面限流、多设备设置冲突语义（409 + re-hydrate 重试）。

## 最终命令结果（详见 VALIDATION.md §1）

- BFF：656 passed；ruff clean
- Web：583 passed；oxlint 0 errors；tsc/build clean；api/settings drift 0
- E2E：desktop 12、mobile 12、a11y 7、rapid-selection 5、ci-smoke 10、
  webdav 4、0018 10、mobile-smoke 3 —— 全部通过

## 阻塞 / 人工步骤

见 VALIDATION.md §5：daemon 代理 override 移除（root，一条命令）；
Chrome Translator 端上翻译建议在 Windows Chrome 复验（Linux 不分发模型）。
