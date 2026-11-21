# 每日要闻

每天北京时间 **07:00**，把国内外新闻按重要性排好序，配上**中文标题、中文摘要、深度解读、名词释义**，
推到你的**邮箱**和 **iPhone（Bark）**，每条都带原文链接。

```
34 个 RSS 源（国际 9 / 科技科学 6 / 中文 19）
   ├─ 只取最近 26 小时
   ├─ 跨源同题合并（标题相似度）
   ├─ DeepSeek 给 100 条候选整批相对打分（0–10，对标 News Minimalist 的重要性标准）
   ├─ 分数最高的一批再复核一次，稳住首位排序
   ├─ 选出 ~30 条宽名单，再让模型识别一次"同一件事的重复报道"并合并
   ├─ 定稿 15 条（其中至少 6 条来自中文源）
   ├─ 抓这 15 条的正文（trafilatura 提取，403 的站点用 headless 浏览器兜底）
   ├─ 若前 15 条里国内新闻不足 2 条，再从剩下的候选里挑 5 条国内要闻补在后面
   ├─ 逐条生成：中文标题 → 2–3 句中文摘要 → 3–4 句解读 → 0–3 个名词释义
   ↓
邮件（HTML）+ Bark 推送
```

## 国际榜 + 国内要闻

- **主榜 15 条**：按全球影响打分排序，中英文媒体混编（`balance.zh_min` 保证至少 6 条来自中文媒体）。
- **国内要闻 5 条**：只收"与中国大陆直接相关"的新闻（国内政策、经济数据、社会事件、企业司法），由打分阶段的 `cn` 字段标记。全球排名天然把它们压在 15 名以外，所以在主榜之后单开一栏，同样配摘要、解读、名词解释。
- **不重复**：如果主榜 15 条里已经有 ≥2 条国内新闻，就不再补（`balance.zh_extra_skip_if`）。
- **解读视角**：解读除讲国际影响外，凡与中国有实际关联（贸易、产业链、能源、外交、科技竞争、周边安全）会点一句"对中国读者意味着什么"，不相关则不硬扯，且不额外加长。

## 分档

| 档位 | 分数 | 含义 |
|---|---|---|
| 重大 | ≥ 7.0 | 改变格局：开战停火、重大政策、突破、大规模伤亡 |
| 重要 | 5.0 – 7.0 | 影响一国多数人或某个行业 |
| 值得一看 | 3.5 – 5.0 | 有信息量，没到改局面的程度 |

没有大事的日子，最高分会停在 5–6 分，版面自然变短——这是刻意的，不为了填满而虚高。

## 本地先跑一遍

```bash
pip install -r requirements.txt
cp .env.example .env          # 填 DEEPSEEK_API_KEY 与推送凭据
python -m playwright install chromium   # 正文抓取的浏览器兜底要用

python -m newsbrief --dry-run  # 只写文件不发消息
start output\brief-2026-11-21.html
```

重发某一天已经生成好的简报（不抓取、不调 AI、不花钱）：

```bash
python -m newsbrief --resend output\brief-2026-11-21.json
```

真实运行一次大约 **2–4 分钟**（其中正文抓取 1–2 分钟），消耗 **3 万 token 左右（约 5 分钱）**。

## 部署到 GitHub Actions

1. 新建仓库，把目录推上去。
2. **Settings → Secrets and variables → Actions** 加四个 secret：
   `DEEPSEEK_API_KEY`、`SMTP_USER`、`SMTP_PASS`、`BARK_URL`。
   （QQ 邮箱的 `SMTP_PASS` 是 **16 位授权码**：设置 → 账户 → 开启 SMTP → 生成授权码。
   Outlook 邮箱先开两步验证，再用"应用密码"当 `SMTP_PASS`，`smtp_host: smtp-mail.outlook.com`、`smtp_port: 587`。）
3. **Actions** 里手动跑一次（勾 `dry_run`），确认产物没问题。
4. 之后每天 UTC 23:00（北京 07:00）自动跑，产物（HTML/TXT/JSON）作为 artifact 保留 14 天。

两个必须知道的坑：

- **cron 用 UTC**，且 GitHub 的定时触发**常延迟 5–30 分钟**。要卡准 07:00，用一台常开的机器
  （小主机 / VPS / 路由器）跑 crontab，或云函数定时触发器。
- **公开仓库连续 60 天没有提交活动**，GitHub 会停掉定时任务，记得偶尔提交一次。

BBC、Guardian、NYT、DW、Al Jazeera 这些源在国内直连不通，在 GitHub Actions（境外机房）上正常；
本地跑会看到它们失败，属正常。

## 成本

| 项目 | 每天 | 每月 |
|---|---|---|
| DeepSeek（deepseek-flash，07:00 属空闲时段，半价） | ≈ 0.05–0.06 元 | ≈ 1.5–1.8 元 |
| GitHub Actions | 公开仓库免费；私有仓库约 2 分钟/天 | 可忽略 |

实测一次完整运行（含正文抽取与同题归并）：10 次调用、输入 24,275 token（缓存命中 2,688）、输出 8,952 token。
按 flash 空闲价（命中 0.02 / 未命中 1 / 输出 4 元每百万）算 ≈ **0.058 元**；
改在 9:00–12:00 或 14:00–18:00 跑，价格翻倍 ≈ 0.115 元。

成本开关：`max_candidates`（送评多少条）、`extraction.max_chars`（每条正文截多少字）、`max_items`。

## 配置（config.yaml）

| 键 | 默认 | 说明 |
|---|---|---|
| `source` | `rss` | 改成 `newsminimalist` 就切成"直接搬运 News Minimalist"，不需要 API key |
| `window_hours` | `26` | 只看最近多少小时的新闻 |
| `per_source_cap` | `15` | 单源最多贡献几条候选，防快讯刷屏 |
| `max_candidates` | `100` | 送去打分的候选数 |
| `max_items` | `15` | 最终推送几条 |
| `balance.zh_min` | `6` | 国内新闻保底条数 |
| `tiers` | 7.0 / 5.0 / 3.5 | 分档阈值与颜色 |
| `scoring.recalibrate_top` | `25` | 复核前 N 条 |
| `dedupe.enabled` / `top_k` | `true` / `30` | 模型识别重复报道的宽名单大小 |
| `extraction.enabled` | `true` | 是否抓正文（关掉省钱但摘要变浅） |
| `extraction.max_chars` | `2600` | 每条正文送进模型的最大字数 |
| `summarising.summary_batch_size` | `6` | 每批写几条（太大易被 max_tokens 截断） |
| `ai.model` | `deepseek-flash` | 也可 `deepseek-v4-pro`（约 3 倍价） |
| `ai.thinking` | `disabled` | 思维链按输出计费且慢，打分用不上 |
| `delivery.email.*` | | SMTP 主机、端口、账号、授权码、收件人（当前 `yexin693@outlook.com`） |
| `delivery.bark.url` | | 形如 `https://api.day.app/<你的 key>` |
| `delivery.bark.max_bytes` | `3400` | 单条 payload 预算；APNs 硬上限 4KB |
| `delivery.bark.split` | `true` | `true` 拆成多条，每条都带完整内容（默认）；`false` 只发一条 |
| `delivery.bark.interval` | `8` | 拆分模式下两条之间的间隔秒数 |
| `delivery.bark.reverse` | `true` | 倒序发送：最后发的才是含第 1 条的那条 |

### Bark：多条通知也要按 1→N 读

iOS 把**最新到达**的通知放在锁屏最上面。所以要让"从上往下滑 = 第 1 条 → 第 20 条"，
发送顺序必须反过来：先发最后一屏，隔 8 秒再发倒数第二屏……**最后发的才是含第 1 条的那条**，
也只有它响铃，其余静音落在同一组里（`sound: none` + `level: passive`）。

实测 20 条拆成 8 屏：

```
21:24:54  8/8  2144 字节   ← 最先发，沉到最下面
21:25:03  7/8  3200 字节
...
21:26:01  1/8  2724 字节   ← 最后发，显示在最上面，唯一响铃
```

如果反过来（正序发送），锁屏上会是 8/8、7/8 … 1/8，看起来像最重要的排最后。
把 `delivery.bark.reverse` 改成 `false` 可以换回正序；`interval` 调大（如 15）可以进一步避免 APNs 抢跑。

> 只想要一条通知：把 `split` 改成 `false`。此时会走"预算分配"策略——排名 1–N 全部保留，
> 用剩余字节从第 1 名开始依次升级成完整块（摘要+解读+名词+链接），升不动的降级为「摘要首句+链接」，
> 再不行就只剩标题行。15 条实测约 3078 字节。

版式走 **Markdown**（`delivery.bark.markdown: true`）：标题是三级标题，分数/来源是行内代码块，
解读是引用块（左侧竖线），名词是粗体标签，末尾是「读原文 →」链接。
如果 Bark 版本较旧、通知里显示成原始 `**` 符号，把它改成 `false` 就退回纯文本。

## 已知限制

- **正文抽取会被反爬挡住**。403 的站点（France 24、BBC 等）走 headless 浏览器兜底，慢几秒；
  付费墙和纯 JS 站点仍可能抓不到，那几条就只能依据导语写。
- **同题合并有两道**：标题相似度 + 一次模型归并。仍会有漏（同一件事两条）或误合（相关但不同）。
- **打分有波动**。同一批新闻换个时间跑，分数可能差 0.3–0.5；档位边界附近会跳档。
- **国内权威媒体的 RSS 覆盖有限**。中新网、人民网、界面、钛媒体、IT之家可用；
  新华社的源没有发布时间会被丢弃。Google News 的中文聚合源在国内不通，在 Actions 上才生效。
- **版权**：摘要是改写不是转载，每条都附原文链接，请以原文为准。

## 排错

| 现象 | 原因 / 处理 |
|---|---|
| `入选 0 条` | 全部低于 3.5 分，或抓取失败：加 `-v` 看每个源的状态 |
| 正文抓取 0/15 | 目标站点全部反爬；开 `-v` 看 `正文 HTTP 403`，浏览器兜底需要 `playwright install` |
| 中文标题为空 | 摘要那一批失败了：看日志里"摘要失败"，调小 `summary_batch_size` |
| 摘要为空但标题正常 | 摘要与标题重复被自动丢弃，属正常 |
| 邮件发不出 | QQ 邮箱要用授权码；465 走 SSL，587 走 STARTTLS，代码自动判断 |
| 邮件进了垃圾箱 | 见下面「为什么会被判垃圾」 |
| Bark 没声音 | `curl -X POST <BARK_URL>` 先试一条 |
| Bark 里显示 `**` `###` 原文 | Bark 版本太旧不认 Markdown：把 `delivery.bark.markdown` 设成 `false` |
| Bark 报 413 | 单条超 4KB：把 `delivery.bark.max_bytes` 调小到 `2600` |

## 为什么邮件会被判垃圾，怎么根治

第一封测试信被 Outlook 扔进了垃圾箱。代码层面已经补了三件事：`Message-ID`、
`Reply-To`、`X-Auto-Response-Suppress`，并且正文是「纯文本 + HTML」双段（不是纯 HTML 群发）。
但这些只是减分项，**根子在发件域**：`@qq.com` 是大量垃圾邮件的来源，Outlook 对它默认不信任，
而你的收件箱在 `@outlook.com`——发件域和收件域完全不同，且没有任何历史互动。

三个选择，按效果排序：

1. **用 Outlook 自己发给自己**（最彻底）。SPF/DKIM/DMARC 全部对齐，发件人=收件人，几乎不会进垃圾箱。
   代价是要一个「应用密码」：Outlook 网页版 → 右上头像 → 查看账户 → 安全 → 两步验证（先开）→
   底部「应用密码」→ 新建。拿到 16 位密码后，配置改成：

   ```yaml
   delivery:
     email:
       smtp_host: smtp-mail.outlook.com
       smtp_port: 587
       username: yexin693@outlook.com
       password: ${SMTP_PASS}      # 填那个应用密码
       from: yexin693@outlook.com
   ```

   注意微软对部分账户关闭了 SMTP AUTH，发送报 `535` 就是被关了，得去账户设置里打开。

2. **换成专用发信服务**（效果同样好，但要注册）。Resend / Brevo 免费额度 100 封/天，
   自带 DKIM 和良好的 IP 信誉，注册后拿一个 API key 即可。缺点是多了个第三方依赖。

3. **保持 QQ + 白名单**（零改动）。在 Outlook 里把这封信从垃圾箱点「不是垃圾」，
   再把 `2652970778@qq.com` 加进「安全发件人」，之后同域来信会稳定进收件箱。
   顺带一提： Outlook 的过滤是按发件人学习的，点过一两次「不是垃圾」之后通常就正常了。

当前默认仍是方案 3（QQ 发信），因为不需要你再提供任何东西。

## 代码结构

```
newsbrief/
  fetch.py      RSS 抓取（线程池、去 utm、时间归一、乱码标点清洗）
  cluster.py    跨源同题合并（CJK 二元组 Jaccard + 稀有词加成）
  rank.py       打分 / 复核 / 模型同题归并 / 中文标题+摘要+解读+名词 / 总览
  extract.py    正文抽取（trafilatura + 正则兜底 + Playwright 兜底）
  llm.py        DeepSeek 客户端（JSON 容错、重试、token 计量）
  render.py     邮件 HTML / 纯文本 / Bark 文案
  deliver.py    SMTP 与 Bark 发送
  main.py       主流程（source: rss）
  nm.py nm_main.py  News Minimalist 搬运通道（source: newsminimalist）
tools/
  selfcheck.py        离线自检（解析、清洗、去重、推送构造）
  smoke_test.py       假 LLM 跑通整条链路
  show_json.py        查看上一次运行的条目与 token 用量
  nm_offline_test.py  搬运通道的离线自检
.github/workflows/daily.yml
```
