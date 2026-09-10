# 40 个真实 AI RSS 来源 — 验证与接入报告

> 日期:2026-09-10 · 环境:本地开发 FreshRSS 1.29.1(与生产同构,官方 greader API 路径)
> 执行脚本:`research/phase2-pocs/feeds/`(validate_feeds.py / probe_round3.py / probe_round4.py / add_selected_feeds.py)
> 证据:`research/phase2-pocs/feeds/feed-validation-report.json`、`probe-results*.json`、`add-results.json`

## 结果总览

```text
40 / 40 PASS  (添加 + FreshRSS 抓取成功 + ≥1 真实条目 + 0 错误 + 0 重复)
订阅:6 → 46   分类:2 → 7   总条目:63 → 4,287
直接 RSS/Atom:40/40(0 个 RSSHub route)
```

备份(变更前):OPML `artifacts/backups/freshrss-opml-before-20260910.xml` + Lumi 全量备份
`lumirss-20260910T155028Z.backup`(freshrss-data + lumi.sqlite,589 KB)。
变更后恢复点:`freshrss-opml-after-20260910.xml`。

## 生产接入(被凭据阻塞,一条命令回放)

生产 FreshRSS(47.100.64.202)为 internal-only,本环境无 SSH 密钥、无 Lumi
basic-auth 凭据,**本轮无法直接写入生产**。生产回放(两种等价方式):

```bash
# 方式 A:FreshRSS 原生导入(服务器上)
docker exec -i lumirss-freshrss php /var/www/FreshRSS/cli/import-for-user.php \
  --user admin < freshrss-opml-after-20260910.xml   # 仅导入 AI · * 六个分类

# 方式 B:greader API(与本地完全一致)
uv run --with httpx python research/phase2-pocs/feeds/add_selected_feeds.py
# (在 production 环境变量 FRESHRSS_* 下运行;脚本仅用官方 API)
```

## 最终 40 源

| # | 分类 | 来源 | Feed URL | 类型 | 最新条目 | FreshRSS |
|---|------|------|----------|------|----------|----------|
| 1 | Labs | OpenAI News | openai.com/news/rss.xml | RSS 2.0 | 2026-09-10 | ✓ 1186 条 |
| 2 | Labs | Google DeepMind News | deepmind.google/blog/rss.xml | RSS 2.0 | 2026-09-08 | ✓ 100 |
| 3 | Labs | Google Research Blog | research.google/blog/rss/ | RSS 2.0 | 2026-09-03 | ✓ 100 |
| 4 | Labs | Google AI Blog | blog.google/technology/ai/rss/ | RSS 2.0 | 2026-09-09 | ✓ 20 |
| 5 | Labs | Microsoft Research | microsoft.com/en-us/research/feed/ | RSS 2.0 | 2026-08-31 | ✓ 10 |
| 6 | Labs | Apple ML Research | machinelearning.apple.com/rss.xml | RSS 2.0 | 2026-09 | ✓ 10 |
| 7 | Labs | NVIDIA Technical Blog | developer.nvidia.com/blog/feed/ | Atom | 2026-09-10 | ✓ 100 |
| 8 | Labs | AWS ML Blog | aws.amazon.com/blogs/machine-learning/feed/ | RSS 2.0 | 2026-09-09 | ✓ 20 |
| 9 | Labs | Hugging Face Blog | huggingface.co/blog/feed.xml | RSS 2.0 | 2026-09-09 | ✓ 861 |
| 10 | Labs | Qwen Blog(替换 Mistral) | qwenlm.github.io/blog/index.xml | RSS 2.0 | 2026-09 | ✓ 44 |
| 11 | Eng | PyTorch Blog | pytorch.org/blog/feed.xml | RSS 2.0 | 2026-09-09 | ✓ 20 |
| 12 | Eng | Weaviate Blog | weaviate.io/blog/rss.xml | RSS 2.0 | 2026-09-08 | ✓ 20 |
| 13 | Eng | vLLM Blog | vllm.ai/blog/rss.xml | RSS 2.0 | 2026-09 | ✓ 50 |
| 14 | Eng | LangChain Blog | langchain.com/blog/rss.xml | RSS 2.0 | 2026-09 | ✓ 100 |
| 15 | Eng | Ollama Blog | ollama.com/blog/rss.xml | RSS 2.0 | 2026-08-30 | ✓ 58 |
| 16 | Eng | Together AI Blog | together.ai/blog/rss.xml | RSS 2.0 | 2026-09 | ✓ 100 |
| 17 | Eng | Anyscale Blog | anyscale.com/rss.xml | RSS 2.0 | 2026-09-07 | ✓ 18 |
| 18 | Eng | Arize AI Blog | arize.com/blog/feed/ | RSS 2.0 | 2026-09-08 | ✓ 10 |
| 19 | Experts | Simon Willison | simonwillison.net/atom/everything/ | Atom | 2026-09-09 | ✓ 30 |
| 20 | Experts | Lilian Weng (Lil'Log) | lilianweng.github.io/index.xml | RSS 2.0 | 2026-07-03 | ✓ 53 |
| 21 | Experts | Sebastian Raschka | sebastianraschka.com/rss_feed.xml | RSS 2.0 | 2026-09-09 | ✓ 150 |
| 22 | Experts | Eugene Yan | eugeneyan.com/rss/ | RSS 2.0 | 2026-06-20 | ✓ 212 |
| 23 | Experts | Andrej Karpathy | karpathy.bearblog.dev/feed/ | Atom | 2026-04-30 | ✓ 10 |
| 24 | Experts | Armin Ronacher | lucumr.pocoo.org/feed.xml | RSS 2.0 | 2026-09-06 | ✓ 10 |
| 25 | Experts | Hamel Husain | hamel.dev/index.xml | RSS 2.0 | 2026-09 | ✓ 20 |
| 26 | Research | Interconnects | interconnects.ai/feed | RSS 2.0 | 2026-09-10 | ✓ 20 |
| 27 | Research | Transformer Circuits | transformer-circuits.pub/feed.xml | Atom | 2026-08-20 | ✓ 56 |
| 28 | Research | AI Alignment Forum | alignmentforum.org/feed.xml | RSS 2.0 | 2026-09-09 | ✓ 10 |
| 29 | Research | LessWrong Curated | lesswrong.com/feed.xml?view=curated | RSS 2.0 | 2026-08-26 | ✓ 10 |
| 30 | Research | The Gradient | thegradient.pub/rss/ | RSS 2.0 | 2026-02-18 | ✓ 15 |
| 31 | Research | arXiv cs.AI | rss.arxiv.org/rss/cs.AI | RSS 2.0 | 2026-09-09 | ✓ 245 |
| 32 | Research | arXiv cs.CL | rss.arxiv.org/rss/cs.CL | RSS 2.0 | 2026-09-09 | ✓ 154 |
| 33 | Research | arXiv cs.LG | rss.arxiv.org/rss/cs.LG | RSS 2.0 | 2026-09-09 | ✓ 252 |
| 34 | Newsletters | Import AI | jack-clark.net/feed/ | RSS 2.0 | 2026-09 | ✓ 10 |
| 35 | Newsletters | Latent Space | latent.space/feed | RSS 2.0 | 2026-09-09 | ✓ 20 |
| 36 | Newsletters | Last Week in AI | lastweekin.ai/feed | RSS 2.0 | 2026-09-09 | ✓ 20 |
| 37 | Newsletters | Ahead of AI | magazine.sebastianraschka.com/feed | RSS 2.0 | 2026-09-09 | ✓ 20 |
| 38 | Newsletters | The Rundown AI | therundown.ai/feed | RSS 2.0 | 2026-09-10 | ✓ 50 |
| 39 | News | MIT Tech Review AI | technologyreview.com/topic/artificial-intelligence/feed | RSS 2.0 | 2026-09-10 | ✓ 10 |
| 40 | News | The Verge AI | theverge.com/rss/ai-artificial-intelligence/index.xml | Atom | 2026-09-10 | ✓ 10 |

构成核对:Labs 10(≥10)· Eng 8(≥8)· Experts 7(≥7)· Research/media 8(≥5,
其中学术 3 ≤5)· Newsletters 5(≥5)· News 2。全部实时验证(HTTP 200 +
feedparser 解析 + 有 2025-2026 条目),`add_selected_feeds.py` 经官方 greader
`subscription/quickadd` 添加、`subscription/edit` 归类,全部抓取成功。

## 拒绝/替换的候选(证据)

| 候选 | 结论 | 证据 | 替代 |
|------|------|------|------|
| Anthropic News | 拒绝:无官方 RSS | `/rss.xml` `/news/rss.xml` `/rss/news.xml` 全 404;rsshub.app 路由本网络 403 | Hugging Face/Qwen |
| Meta AI Blog | 拒绝:无 RSS | `ai.meta.com/blog/{feed,rss}/`、about.fb.com 分类 feed 全 404 | NVIDIA/AWS |
| Mistral AI | 拒绝:CDN 错误 content-type | `/rss.xml` 返回 200 但 `text/plain`,SimplePie 拒绝(`add-results.json` #10) | Qwen Blog |
| Cohere | 拒绝:200-but-HTML | `/blog/rss.xml`、`txt.cohere.com/rss/` 均 200 无条目 | — |
| Allen Institute (AI2) | 拒绝:无 RSS | `/blog/{feed,rss,feed.xml}` 全 404 | — |
| EleutherAI | 拒绝:无 RSS | 全变体 404 | Transformer Circuits |
| W&B / Modal / Replicate / Lightning / Groq / LlamaIndex / Evidently | 拒绝:无可解析 feed(200-HTML 壳或 404;replicate TLS 指纹阻断) | `probe-full.log`、round3/4 | PyTorch/Weaviate/vLLM 等 |
| BAIR | 拒绝(本环境):SSL 握手超时 | 宿主与容器均 ConnectTimeout | Apple ML Research |
| The Batch / TLDR / Ben's Bites | 拒绝:404 | round2/3 证据 | The Rundown AI / Towards AI |
| MarkTechPost、Towards AI、Jay Alammar、Chip Huyen、Vicki Boykis、Addy Osmani、TechCrunch AI、Ars Technica AI、Towards Data Science、fast.ai | 验证通过但未入选 | 构成约束/更新频率/主题相关度 | —(保留在候选池 JSON) |

## 维护说明

- 候选池与原始验证数据保留在 `research/phase2-pocs/feeds/*.json`,失效源替换
  时直接改 `add_selected_feeds.py` 的 `SELECTED` 表重跑(幂等:已存在的 URL
  quickadd 返回已订阅)。
- 高体积源(arXiv ×3 ≈ 650 条/周、OpenAI/HF 历史回填 >800 条)是条目增长
  主力;生产 1.6GB 服务器如需限流,可在 FreshRSS 中把 arXiv 的 TTL 调大或
  限存 articles 数(FreshRSS 原生支持,不涉及代码)。
