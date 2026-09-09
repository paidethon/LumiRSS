# Backup & Restore（备份与恢复）

> 备份相关操作与事实只维护在本文；配置键见
> [../reference/configuration.md](../reference/configuration.md)。

## 两条路径

1. **UI / API（应用级，功能最全）**：设置 →「数据控制」（配置迁移 /
   完整备份 / 备份历史 / WebDAV / 恢复同页）。
2. **`./lumirss backup` / `./lumirss restore`（卷级，整机运维）**：
   把 `lumi-data`、`freshrss-data` 卷打成 tar.gz 存到 `./backups/`
   （`LUMIRSS_BACKUP_DIR` 可改），连同 `.env.prod` 与 compose 文件一起
   归档；`./lumirss restore <backup.tar.gz> [--yes]` 停 bff → 覆盖卷 →
   启动 → 健康检查（破坏性操作，需输入 `RESTORE` 或 `--yes`）。

## 应用级备份内容

- lumi.sqlite（在线备份 API）+ FreshRSS 数据目录（只读卷 + SQLite
  online backup，含 config.php 与用户 db.sqlite）。
- 版本化 manifest（backupSchemaVersion=1）+ 每文件 SHA-256。

## 敏感性

- **备份必须当作敏感文件保管**：Lumi 自身的秘密值（AI/WebDAV/RSSHub/
  FreshRSS API 密码、auth 哈希——见 manifest.secretPolicy.excludedSecrets）
  **不进备份**，恢复后需重新配置；但 **FreshRSS 数据目录本身可能含凭据
  敏感材料**（如 FreshRSS 用户口令哈希、其自身配置），归档不是
  "无敏感内容"。
- 存储：本机 `data/backups/` 限制文件系统权限；WebDAV 传输走 TLS
  （http 仅允许私网/回环），远端目录需访问控制。切勿把备份归档提交到
  Git 或上传到不受信位置。

## WebDAV

- 服务器端上传；密码 write-only（永不回显）；http 仅允许私网/回环地址；
  重定向限同源、有界响应。
- `GET /api/v1/backups/remote` 列出远端备份。

## 完整备份能力预检与 FreshRSS 权限边界

`GET /api/v1/backups/capabilities` 在点击前如实回答"完整备份现在能包含
什么"：FreshRSS 数据目录是否配置/存在/可读、数据库类型（外部
MySQL/PostgreSQL 不在数据目录里 → 明确拒绝并提示直接备份数据库）、
将包含的组件清单。后端执行时用同一预检逻辑再校验。

FreshRSS 把 `data/users/<user>/` 建为 `0770 root:www-data`，因此：

- **生产 Compose（支持拓扑）**：`docker-compose.prod.yml` 已给 BFF 容器
  `group_add: ["33"]`（www-data 组），BFF（uid 10001）可只读遍历。
  旧部署升级后需 `up -d --force-recreate bff` 重建容器生效。
- **开发栈（宿主机 BFF + 容器 FreshRSS）**：完整备份需一次性迁移到
  bind mount（见 `docker-compose.dev-backup.yml` 头注释，数据保留可回滚），
  并对数据目录执行一次
  `docker exec freshrss sh -c 'chmod -R a+rX /var/www/FreshRSS/data'`
  （之后新写入文件若再次变严，预检会如实报 `unreadable_entries`，
  重跑同一条命令即可）。BFF 侧在 `services/bff/.env` 设
  `FRESHRSS_DATA_DIR` 指向同一目录。
- 预检/执行对"目录存在但部分不可读"一律诚实失败
  （`unreadable_entries`），绝不产出缺用户数据库的"假完整包"。

## 恢复

- 单并发 job；阶段真实上报；**恢复前自动创建当前状态安全备份**；
  恢复需显式输入 `RESTORE`。损坏 checksum / 不兼容版本会被拒绝。
- FreshRSS 数据恢复为**离线恢复**：文件就绪于
  `data/restore-staging/restore-ready/freshrss/`，operator 按官方 compose
  步骤自行覆盖 FreshRSS 卷（Lumi 不写运行中的 FreshRSS）。
- 恢复后残留的 interrupted 记录是正常审计：快照中的陈旧运行态被标记为
  interrupted。

## 灾难恢复流程

1. 部署全新栈（[deploy.md](deploy.md) §1/§3）。
2. 取回最近备份（本机卷或 WebDAV）。
3. 「数据控制 → 备份历史 → 从此备份恢复」→ 预览校验 → 输入 `RESTORE` 执行。
4. FreshRSS 数据按上文离线恢复；`/health/ready` + 阅读流程验证。

## 磁盘维护

`data/backups/` 与 `data/restore-staging/` 定期清理（staging 会话与
24h 前下载会自动清理）。
