# 邀请成员（运营者指南）

> 面向运营者（owner / admin）。LumiRSS 默认**邀请制多账户**：新成员经
> 运营者发出的一次性限时邀请激活；可选公开注册是实例级开关、默认关闭
> （见 §6）。每个账号拥有独立的订阅、阅读状态、资料库、AI 配置与
> FreshRSS 绑定。管理界面入口：`/admin`（仅 owner / admin 角色可见）；
> 对应 API 前缀 `POST|GET /api/v1/admin/*`。

## 1. 发出邀请 {#invite}

1. 以运营者账号登录，打开 **`/admin` → 邀请**（或 `POST /api/v1/admin/invites`）；
2. 设置有效期（默认 72 小时，上限 30 天）与可选备注；
3. 系统返回一次性邀请链接（`/activate?token=…`）。**原始 token 只显示这一次**
   ——数据库只存其 SHA-256，关掉弹窗后无法再查看，只能作废重发；
4. 把链接私下交给受邀者。邀请可随时在 `/admin` 撤销（未使用才可撤销）。

## 2. 受邀者激活 {#activate}

受邀者打开邀请链接，在激活页自设用户名与密码：

- 用户名：3–32 个字符，小写字母 / 数字 / `-` / `_`，字母或数字开头；
- 密码：至少 8 个字符（bcrypt 哈希存储，明文任何地方不落盘）。

激活即建立完全独立的账号；会话语义与所有账号一致（256-bit opaque
session，`__Host-` Cookie）。受邀者**不需要**也无法接触运营者的
FreshRSS 凭据。

## 3. 准备 FreshRSS 账号池（激活前做） {#pool}

RSS 订阅/已读/收藏的真源是每个账号自己的 FreshRSS 账号。运营者用
`scripts/freshrss_pool.sh`（部署侧、官方 FreshRSS CLI）预建空账号并登记
进 Lumi 池：

```bash
FRESHRSS_ADMIN_PASSWORD=… LUMI_ADMIN_PASSWORD=… \
scripts/freshrss_pool.sh 3 http://freshrss admin http://127.0.0.1:8000
```

- 激活时 BFF **原子分配**一个池账号——两个并发激活不可能拿到同一账号；
- **池空 ≠ 不能用**：账号照常激活，RSS 绑定显示「待就绪」，之后补池即可；
- 全程没有共享凭据回退；API 密码只存部署侧 secrets 文件（0600），不入库；
- 池状态在 `/admin`（或 `GET /api/v1/admin/pool`）可见：ready / assigned。

## 4. 暂停 / 恢复成员 {#pause-resume}

`/admin` → 成员列表（或 `POST /api/v1/admin/users/{id}/pause` /
`/resume`）：

- **暂停**：成员立即无法登录（新登录被拒），已有会话一并失效；数据保留；
- **恢复**：成员可重新登录，一切数据原样。
- 运营者本人（owner 角色）不可被暂停；需要收回权限时改用重置密码。

## 5. 重置成员密码 {#reset-password}

`/admin` → 成员 → 重置密码（或 `POST /api/v1/admin/users/{id}/reset-password`）：

1. 系统给该账号安装一个无人知晓的随机密码并撤销其全部会话；
2. 返回一条 24 小时有效的**恢复邀请**（原始 token 只显示一次）；
3. 把恢复链接交给该成员，他在 `/activate` 页面自设新密码。

不存在邮件发送环节——不假装发信，链接由运营者亲手转交。

## 6. 可选公开注册（默认关闭） {#registration-policy}

- **升级后默认关闭，需 admin 显式开启**：`GET/PUT
  /api/v1/admin/registration-policy`（admin 会话）。开关存控制库
  （`allow_public_registration`），不是 env；每次变更落审计（含改动前
  后值与操作者）。
- 开启后 `POST /api/v1/auth/register` 开放自助注册（路径限流 10 次/60 秒
  并纳入 CSRF Origin 校验）；**角色恒为 member**，客户端不可指定；
  FreshRSS 池原子分配，池空则诚实显示「待就绪」，之后补池即可（同 §3）。
  当前 Web 界面尚未提供注册入口与策略开关，均经 API 操作。
- 关闭时注册统一返回 403 `registration_disabled`，不泄露用户名是否存在。
  是否在公网实例开启由运营者自行评估暴露面（限流与 CSRF 只是边界之一，
  不是公共互联网加固保证）；见
  [../decisions/0006-public-registration.md](../decisions/0006-public-registration.md)。

## 相关

- 数据分层（控制库 + 每用户库）与身份路由：
  [../explanation/architecture.md](../explanation/architecture.md)；
- FreshRSS 池脚本安全边界：`scripts/freshrss_pool.sh` 头注释；
- 成员登录不了？见 [troubleshoot.md](troubleshoot.md)。
