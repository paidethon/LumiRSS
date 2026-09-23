# 可选服务（按需 LibreTranslate 机器翻译）

> 面向自托管 operator。对应实现：`docker-compose.translate.yml`、
> `./lumirss translate`、BFF 的 LibreTranslate 引擎
> （`services/bff/src/lumirss/ai_translation_segments.py`）。配置键语义
> 统一见 [../reference/configuration.md](../reference/configuration.md)。

## 1. 什么时候用

阅读翻译有三种引擎（设置 → 翻译）：

| 引擎 | 运行位置 | 依赖 |
|---|---|---|
| browser | 浏览器本地 | 无（默认开箱可用） |
| libretranslate | 服务端自托管（本文，经 BFF 调用） | 本节的可选服务 |
| AI | 云端 LLM（用户自带 API key） | 「AI」设置里配置 |

LibreTranslate 适合"不想把正文发给云端 LLM、又想要服务端整篇机器翻译"
的场景：本地推理、免费、无外部请求（模型装好后启动也不联网）。

它是**按需（on-demand）**的：不在 `./lumirss deploy` / `update` 的默认
栈里，`restart: "no"` 也不会随宿主重启自动拉起——需要时显式启动，
用完显式停止。这是为 2 GB 宿主刻意设计的。

## 2. 资源预期（诚实数字）

- 镜像 `libretranslate/libretranslate:v1.9.6` ~200 MB；
- **首次启动**下载 en/zh 翻译模型 **~200-400 MB 磁盘**，写进
  `lumirss-libretranslate-models` 卷，只发生一次（之后启动不再联网更新；
  删除该卷即可回收磁盘，下次启动会重新下载）；
- 运行内存 **~300-400 MB**（单 worker + en/zh 模型；容器上限
  `mem_limit: 420m` / `mem_reservation: 256m` / `cpus: 1.0`）；
- **2 GB 宿主警告**：全栈（web/bff/freshrss/rsshub）已经接近内存上限，
  LibreTranslate 只适合**按需启动、用完即停**；不要把它加入常驻栈；
- 只挂载这一个命名卷，无其它持久化；上游调用有 20s 超时（BFF 侧）。

## 3. 启动 / 停止 / 状态

```bash
./lumirss translate up      # 启动（首次含模型下载，几分钟；Docker Hub 拉镜像）
./lumirss translate status  # 容器状态 + 健康 + en→zh 小探测
./lumirss translate stop    # 停止（容器与模型卷保留，下次 up 复用）
```

手工等价：

```bash
docker compose -f docker-compose.prod.yml -f docker-compose.translate.yml \
  up -d libretranslate
```

`translate status` 默认附带一次 en→zh "hello" 探测（本地免费、5s 超时，
只打印**输出长度**、不打印内容）；`LUMIRSS_TRANSLATE_PROBE=0` 可关掉。

宿主侧只发布 **loopback** 端口 `127.0.0.1:50050`（`LUMIRSS_TRANSLATE_PORT`
可改，见 [../reference/configuration.md](../reference/configuration.md)），
仅供 operator 在宿主机上 curl 验证，**不要放行到公网**。

## 4. 指向 Lumi BFF

1. `./lumirss translate up` 并等健康（首次含模型下载）；
2. 打开 Web「设置 → 翻译」，引擎选
   「本地机器翻译 — 自托管服务器执行（LibreTranslate，经 BFF）」；
3. 服务地址填 **`http://lumirss-libretranslate:5000`**——这是 compose
   内网服务名，BFF 容器可以直接解析。**不要**填 `127.0.0.1:50050`：
   那是宿主 loopback，BFF 容器里的 127.0.0.1 是它自己，不通；
4. API Key 留空即可（无鉴权实例）。要填也安全：key 只存 BFF 服务端
   SecretsStore（write-only，浏览器永远读不回）；
5. 该调用不需要 `LUMIRSS_FETCH_ALLOW_PRIVATE_HOSTS`：那个 allow-list
   只管 feed/来源取回路径，LibreTranslate 引擎是独立的出站 httpx
   客户端（20s 超时）直接访问内网地址。

## 5. 验证

```bash
# 1) 容器健康（首次启动模型下载期间是 starting，属预期）
docker inspect --format '{{.State.Health.Status}}' lumirss-libretranslate

# 2) /languages 应同时列出 en 与 zh
curl -s http://127.0.0.1:50050/languages | python3 -m json.tool

# 3) 一次真实翻译（探测只打印输出长度，不打印内容）
./lumirss translate status
```

BFF 链路：设置 → 翻译 → LibreTranslate「测试连接」按钮
（`POST /api/v1/settings/translation/libretranslate-test`，内部
`GET /languages`）应提示连接成功；然后在阅读页选 libretranslate 引擎
实际翻译一篇文章（zh-CN ↔ en 均已安装）。

## 6. 不用它的日子

不启动就是零成本：没有容器、没有端口、没有磁盘占用（模型卷只有跑过
一次才存在）。基础的三种翻译模式（browser / AI / 自托管）互不影响，
默认 browser 引擎不依赖任何可选服务。
