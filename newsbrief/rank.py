# -*- coding: utf-8 -*-
"""The judgment layer: significance scoring, summaries, daily overview.

The scoring method follows News Minimalist: rate each story by how much it
changes the existing state of the world, and rate the whole batch relatively
instead of judging headlines in isolation.
"""

from __future__ import annotations

import logging
from datetime import datetime

from .llm import ChatClient, LLMError
from .models import Item

log = logging.getLogger(__name__)

CATEGORIES = [
    "地缘政治", "经济金融", "科技", "社会", "科学健康", "环境气候",
    "能源资源", "军事安全", "法律治理", "文化教育", "其他",
]

SCORE_SYSTEM = """你是一个新闻重要性评分器。你的任务不是判断新闻"好不好看"，而是判断它"在多大程度上改变了世界的既有状态"。

请综合以下维度判断（不要机械加权，用常识把它们揉在一起）：
- 规模：有多少人受到影响
- 幅度：改变了多少既有的状态——新政策落地、战争爆发、公司崩塌、科学突破，都算改变
- 意外性：是否超出此前的预期
- 传导性：会不会引发后续的连锁重大事件
- 时效性：变化是否正在发生
- 可行动性：读者能否据此调整自己的判断或决策
- 确定性：已确认的事实给高分，传闻、预测、单方说法要降分
- 正向补偿：重大突破、救援成功、协议达成同样是重大事件，不要只奖励坏消息

锚点（这是全球绝对标准，不要因为这一批里没有大事就抬高分数）：
9.0-10.0 全球格局级：大国开战或停火、核武器相关事件、全球性金融危机、改变人类生活的科学突破、大国领导人非常规更替
7.0-8.9  多国级：影响多个国家或数亿人的政策与协议、重大科技突破、造成千人以上伤亡的灾难、国际组织的重大裁决
5.0-6.9  国家级：影响一国多数人的政策、全国性选举结果、大型企业的重大变故、重要司法判决
3.0-4.9  群体级：影响特定行业或群体、区域性事件、有价值的行业变化
0.0-2.9  噪声级：体育赛事、娱乐八卦、明星动态、地方民生琐事、纯商业宣传、日常股价波动、产品促销

规则：
1. 先把整批新闻在心里按重要性从高到低排一次序，再给分数——相对排序比孤立打分可靠得多。
2. 如果整批确实没有重大事件，就让最高分停在 5-6 分区间，不要为了"填满版面"而虚高。
3. 同一事件的不同报道视为同一件事，给相同分数。
4. 候选里同时有中文媒体和外语媒体。按"对世界的实际影响"打分，不要因为语言或来源不同而系统性偏高偏低；国内的经济数据、重大政策、灾害事故、司法判决只要影响够大，同样可以进 7 分以上。
5. 只依据给定的标题和导语判断，不要脑补没有提供的信息。
6. 只输出 JSON，不要任何解释性文字。"""

SCORE_USER = """当前时间：{now}
本批共 {n} 条候选（属于今天全部 {total} 条候选中的一批）。

{listing}

请输出 JSON：
{{"items":[{{"id":1,"score":7.5,"category":"地缘政治","cn":false,"reason":"停火生效，影响千万人"}}]}}

要求：
- id 必须是上面列表里的编号，不要漏、不要编。
- score 为 0-10 的一位小数。
- category 只能取：{categories}
- cn：这条新闻是否与中国大陆直接相关（国内政策、经济数据、社会事件、企业司法、民生治理 → true；涉及中国的国际关系、台海博弈、对外摩擦 → false）。
- reason 不超过 24 字，说明"为什么重要"，不要复述标题。"""

RECAL_SYSTEM = """你是新闻重要性评分器，正在进行一轮"复核"。
下面这些新闻在初评中得分较高。请用与初评完全相同的全球绝对标准再打一次分。

特别注意：
- 不要因为"它们已经是被挑出来的一批"就整体抬高分数。
- 这批里如果只有 5 分水平的事件，最高分就应该是 5 分。
- 你的任务是区分它们之间的相对高下，而不是给它们集体加分。

只输出 JSON。"""

RECAL_USER = """当前时间：{now}
以下是初评分数较高的 {n} 条：

{listing}

请用同一套绝对标准重新打分，输出 JSON：
{{"items":[{{"id":1,"score":7.5,"category":"地缘政治","reason":"停火生效，影响千万人"}}]}}"""

SUMMARY_SYSTEM = """你是中文新闻编辑，负责把中文和外语新闻统一写成读者能看懂、能判断的中文简报。

对每条新闻输出四项：
- title_zh：中文标题。外国人名、地名、机构名用中文媒体的通行译名，没有通行译名就保留原文；不要逐字直译，要像中文媒体那样写得通顺、能一眼看懂。
- summary：2 到 3 句事实概括，讲清"谁做了什么、结果如何、关键数字是多少"。原文是外文时，这里是翻译加压缩，不是逐句对译。只写材料里提供了的事实。
- insight：3 到 4 句解读，不超过 200 字。回答三件事：这件事的背景和前因是什么、它真正改变的是什么（不要复述 summary）、接下来几天值得盯哪个具体信号。有判断，但判断要落在事实上，不要泛泛而谈"影响深远"。如果这件事和中国有实际关联（贸易、产业链、能源、外交、科技竞争、周边安全），用其中一句点出对中国读者意味着什么；没有关联就不要硬扯，也不要因此写得更长。
- terms：读者可能看不懂的名词，0 到 3 条。包括：机构缩写（如 OPEC+、ICC）、制度与法律名词（如"授权使用武力""反倾销"）、新技术概念（如"mRNA 疫苗平台"）、不太常见的地缘名词。每条给一句解释，说清它是什么、跟这条新闻什么关系。没有生词就返回空数组，不要硬凑。

硬性要求：
- 四项都用中文写（专有名词保留原文写法）。
- summary 必须提供标题以外的信息（具体数字、对象、条件、结果），标题已经说了的不要重复。
- 材料里有正文时，summary 和 insight 要以正文为准；正文与导语冲突时以正文为准。
- 如果材料只有导语、信息很少，就写得克制些，只补一个可核实的细节，不要为了凑字数改写标题或编造背景。
- 不使用"据悉""业内人士""引发热议""值得关注""引发广泛讨论"这类空话。
- 不推测动机，不添加情绪，不写评论文章式的抒情句。
- 文本里需要引号时一律用中文引号“”，不要用英文双引号 "，否则会破坏 JSON。
- 绝不编造材料里没有的细节；数字、金额、伤亡人数必须与原文一致。
- 只输出 JSON。"""

SUMMARY_USER = """{listing}

请输出 JSON：
{{"items":[{{"id":1,"title_zh":"…","summary":"…","insight":"…","terms":[{{"term":"…","explain":"…"}}]}}]}}

title_zh 不超过 30 字，summary 不超过 150 字，insight 不超过 200 字，每条 term 的 explain 不超过 40 字。id 必须与输入一一对应，不要漏。"""

OVERVIEW_SYSTEM = """你是《世界要闻》的主编。基于今天入选的新闻，用 2-3 句话给读者一个总览：今天世界最主要的变化是什么，彼此之间有没有关联。

要求：
- 只描述事实层面的趋势，不预测、不抒情、不点评价值观。
- 不要用"今天""今日"开头。
- 如果确实没有大事，就直白地说这是一个平静的日子，不要硬凑。
- 中文，不超过 110 字，纯文本，不要 Markdown。"""

OVERVIEW_USER = """{listing}

请写出今天的总览。"""


DEDUPE_SYSTEM = """你是新闻编辑，任务是识别"同一件事被多家媒体分别报道"。

同一件事在不同媒体上措辞差别往往很大，要认出它们：
- "俄罗斯导弹落入波兰" / "三枚俄方飞行物落入波兰" → 同一件事
- "丹麦指控俄策划暗杀" / "欧盟委员会主席谴责俄在丹麦暗杀阴谋" → 同一件事
- "伊朗击落美军无人机" / "伊朗称在锡里克岛击落 MQ-1" → 同一件事

以下**不算**同一件事，不要合并：
- 同一方在同一天做的两件不同的事（比如同一天通过的两项不同法案）
- 一个事件本身，和各国对它的反应或评论
- 同一主题下不同人物、不同公司、不同地点的消息
- 同一场冲突中的两次不同袭击（不同时间、不同地点、不同目标）

这批候选里重复报道通常很多（三成以上），请认真找。

只输出 JSON，不要解释。"""

DEDUPE_USER = """当前时间：{now}
下面是 {n} 条候选（编号｜来源｜标题｜导语）：

{listing}

请按"同一件事"分组，输出 JSON：
{{"groups":[[1,2],[3],[4],[5,6]]}}

要求：
- 每个编号必须出现且只出现一次。
- 主体相同、核心动作相同、时间相近，就合并成一组，哪怕标题用词完全不同。
- 确实独一无二的就单独成组。"""


def _format_listing(items: list[Item], id_map: dict[int, str]) -> str:
    return "\n".join(
        f"[{idx}] {it.source_name} ｜ {it.title} ｜ {it.lead[:220]}"
        for idx, it in id_map.items()
    )


def _assign(items: list[Item], payload: dict, apply) -> int:
    """Map model output back onto items; returns how many were applied."""
    rows = payload.get("items")
    if not isinstance(rows, list):
        return 0
    applied = 0
    by_index = {str(i + 1): it for i, it in enumerate(items)}
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = str(row.get("id", "")).strip()
        target = by_index.get(key)
        if target is None:
            continue
        if apply(target, row):
            applied += 1
    return applied


def score_items(client: ChatClient, items: list[Item], cfg: dict) -> None:
    batch_size = int(cfg.get("batch_size", 60))
    categories = "、".join(CATEGORIES)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    total = len(items)

    for start in range(0, total, batch_size):
        batch = items[start : start + batch_size]
        id_map = {i + 1: it for i, it in enumerate(batch)}
        prompt = SCORE_USER.format(
            now=now,
            n=len(batch),
            total=total,
            listing=_format_listing(batch, id_map),
            categories=categories,
        )
        log.info("打分 第 %d 批（%d 条）", start // batch_size + 1, len(batch))
        try:
            payload = client.chat_json(SCORE_SYSTEM, prompt)
        except LLMError as exc:
            log.error("  打分失败，本批按 0 分处理: %s", exc)
            continue

        def apply(item: Item, row: dict) -> bool:
            try:
                score = float(row.get("score"))
            except (TypeError, ValueError):
                return False
            item.score = max(0.0, min(10.0, score))
            item.reason = str(row.get("reason", ""))[:60]
            item.cn = str(row.get("cn", "")).strip().lower() in ("true", "1", "yes", "y")
            category = str(row.get("category", "")).strip()
            item.category = category if category in CATEGORIES else "其他"
            return True

        applied = _assign(batch, payload, apply)
        if applied < len(batch) * 0.6:
            log.warning("  只解析回 %d/%d 条，可能有缺漏", applied, len(batch))


def recalibrate(client: ChatClient, items: list[Item], cfg: dict) -> None:
    """Second pass over the strongest stories to stabilise the top ordering."""
    top_k = int(cfg.get("recalibrate_top", 25))
    if top_k <= 0:
        return
    pool = [it for it in items if it.score > 0]
    pool.sort(key=lambda it: it.score, reverse=True)
    pool = pool[:top_k]
    if len(pool) < 8:
        return

    id_map = {i + 1: it for i, it in enumerate(pool)}
    prompt = RECAL_USER.format(
        now=datetime.now().strftime("%Y-%m-%d %H:%M"),
        n=len(pool),
        listing=_format_listing(pool, id_map),
    )
    log.info("复核打分：前 %d 条", len(pool))
    try:
        payload = client.chat_json(RECAL_SYSTEM, prompt)
    except LLMError as exc:
        log.warning("  复核失败，沿用初评: %s", exc)
        return

    def apply(item: Item, row: dict) -> bool:
        try:
            score = float(row.get("score"))
        except (TypeError, ValueError):
            return False
        item.score = max(0.0, min(10.0, score))
        category = str(row.get("category", "")).strip()
        if category in CATEGORIES:
            item.category = category
        reason = str(row.get("reason", "")).strip()
        if reason:
            item.reason = reason[:60]
        return True

    _assign(pool, payload, apply)


def summarize_items(client: ChatClient, items: list[Item], cfg: dict) -> None:
    if not items:
        return
    batch_size = int(cfg.get("summary_batch_size", 6))

    def run(batch: list[Item]) -> None:
        id_map = {i + 1: it for i, it in enumerate(batch)}
        rows = []
        for idx, it in id_map.items():
            if it.body:
                rows.append(
                    f"[{idx}] 来源：{it.source_name}｜标题：{it.title}｜导语：{it.lead[:220]}"
                    f"｜正文：{it.body[:1800]}"
                )
            else:
                rows.append(
                    f"[{idx}] 来源：{it.source_name}｜标题：{it.title}｜导语：{it.lead[:300]}"
                    f"｜正文：（未取到，只依据标题和导语）"
                )
        listing = "\n".join(rows)
        try:
            payload = client.chat_json(SUMMARY_SYSTEM, SUMMARY_USER.format(listing=listing))
        except LLMError as exc:
            # Long batches can overrun max_tokens and come back as broken JSON;
            # halving them usually rescues the batch.
            if len(batch) > 1:
                log.warning("  摘要失败（%d 条），拆半重试: %s", len(batch), exc)
                mid = len(batch) // 2
                run(batch[:mid])
                run(batch[mid:])
            else:
                log.error("  摘要失败（单条），跳过: %s", exc)
            return

        def apply(item: Item, row: dict) -> bool:
            summary = str(row.get("summary", "")).strip()
            insight = str(row.get("insight", "")).strip()
            title_zh = str(row.get("title_zh", "")).strip()
            if not summary:
                return False
            item.summary = summary
            item.insight = insight
            if title_zh:
                item.title_zh = title_zh[:60]
            terms = row.get("terms")
            if isinstance(terms, list):
                cleaned = []
                for term in terms[:3]:
                    if not isinstance(term, dict):
                        continue
                    name = str(term.get("term", "")).strip()[:40]
                    explain = str(term.get("explain", "")).strip()[:80]
                    if name and explain:
                        cleaned.append({"term": name, "explain": explain})
                item.terms = cleaned
            return True

        _assign(batch, payload, apply)

    for start in range(0, len(items), batch_size):
        batch = items[start : start + batch_size]
        log.info("写摘要 第 %d 批（%d 条）", start // batch_size + 1, len(batch))
        run(batch)


def dedupe_by_topic(client: ChatClient, items: list[Item], cfg: dict) -> list[Item]:
    """Merge items the model judges to be the same story, keeping the best one.

    Title similarity only catches near-identical headlines; different outlets
    often phrase the same event quite differently ("Russian projectiles hit
    Poland" vs "Russian missiles hit Poland"). One cheap call over the top
    candidates fixes most of that.
    """
    top_k = int(cfg.get("top_k", 30))
    if not cfg.get("enabled", True) or len(items) < 4:
        return items

    pool = items[:top_k]
    id_map = {i + 1: it for i, it in enumerate(pool)}
    listing = "\n".join(
        f"[{idx}] {it.source_name}｜{it.title}｜{it.lead[:90]}" for idx, it in id_map.items()
    )
    prompt = DEDUPE_USER.format(
        now=datetime.now().strftime("%Y-%m-%d %H:%M"), n=len(pool), listing=listing
    )
    log.info("同题归并：%d 条候选", len(pool))
    try:
        payload = client.chat_json(DEDUPE_SYSTEM, prompt)
    except LLMError as exc:
        log.warning("  同题归并失败，沿用标题去重结果: %s", exc)
        return items

    groups = payload.get("groups")
    if not isinstance(groups, list):
        return items

    seen: set[int] = set()
    merged: list[Item] = []
    for group in groups:
        if not isinstance(group, list):
            continue
        picks: list[Item] = []
        for raw in group:
            try:
                key = int(str(raw).strip())
            except (TypeError, ValueError):
                continue
            item = id_map.get(key)
            if item is None or key in seen:
                continue
            seen.add(key)
            picks.append(item)
        if not picks:
            continue
        picks.sort(key=lambda it: (it.weight, -it.published.timestamp()), reverse=True)
        keeper = picks[0]
        for other in picks[1:]:
            if other.source_name not in keeper.also_reported:
                keeper.also_reported.append(other.source_name)
            if other.score > keeper.score:
                keeper.score = other.score
            if len(other.lead) > len(keeper.lead):
                keeper.lead = other.lead
        merged.append(keeper)

    leftovers = [it for idx, it in id_map.items() if idx not in seen]
    merged.extend(leftovers)
    if len(merged) < len(items):
        merged.extend(items[top_k:])
    merged.sort(key=lambda it: it.score, reverse=True)
    log.info("  归并后 %d 条（原 %d 条）", len(merged), len(items))
    return merged


def make_overview(client: ChatClient, items: list[Item]) -> str:
    if not items:
        return ""
    listing = "\n".join(
        f"- {it.title}（{it.source_name}，{it.score:.1f}分）" for it in items[:12]
    )
    try:
        text = client.chat(
            OVERVIEW_SYSTEM, OVERVIEW_USER.format(listing=listing), json_mode=False
        )
    except LLMError as exc:
        log.warning("总览生成失败: %s", exc)
        return ""
    return " ".join(text.split())[:400]


_PUNCT_RE = None


def _plain(text: str) -> str:
    global _PUNCT_RE
    if _PUNCT_RE is None:
        import re

        _PUNCT_RE = re.compile(r"[\s，。、：；·—\-–\"'“”‘’（）()【】\[\]!?！？…]")
    return _PUNCT_RE.sub("", text)


def drop_echo_summaries(items: list[Item], threshold: float = 0.82) -> None:
    """Blank summaries that just restate the headline (a common LLM slip)."""
    import difflib

    for item in items:
        if not item.summary:
            continue
        first = item.summary.replace("。", "\n").split("\n")[0]
        title = _plain(item.title)
        body = _plain(first)
        if len(body) < 8 or not title:
            continue
        if difflib.SequenceMatcher(None, title, body).ratio() > threshold:
            log.debug("摘要与标题重复，已省略：%s", item.title[:40])
            item.summary = ""
