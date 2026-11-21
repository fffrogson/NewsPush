# -*- coding: utf-8 -*-
"""Render the HTML template with synthetic items covering every tier.

Purely a layout check: no network, no LLM, no delivery. The wording is hand
written on purpose — it shows what a good summary looks like (adds facts the
headline does not already carry) versus a lazy one that just repeats it.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from newsbrief.models import Item  # noqa: E402
from newsbrief.render import DEFAULT_TIERS, group_by_tier, render_html  # noqa: E402

MOMENT = datetime(2026, 11, 21, 7, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

# (分数, 分类, 标题, 摘要, 解读)
SAMPLES = [
    (
        9.2,
        "地缘政治",
        "中美两国宣布重启高层经贸对话机制",
        "首轮磋商定于下月在日内瓦举行，双方同时放宽了 87 类商品的关税豁免，为 2023 年以来首次。",
        "两国同时松口，说明比起关税清单，双方现在更担心的是各自国内的增长失速。",
    ),
    (
        8.1,
        "经济金融",
        "美联储宣布将基准利率下调 25 个基点",
        "利率区间降至 3.75%–4.00%，为今年第二次降息；点阵图显示多数委员预计年内还有一次。",
        "降息本身早被市场消化，真正的新信息是点阵图比上次会议更偏鸽。",
    ),
    (
        7.4,
        "科技",
        "欧盟正式通过对通用人工智能模型的分级监管细则",
        "高风险模型须在明年 6 月前完成合规审计，违规最高按全球营收 3% 罚款。",
        "训练成本会因此上升，但受影响最大的其实是想进入欧洲市场的开源团队。",
    ),
    (
        5.8,
        "科学健康",
        "一项覆盖 12 万人的队列研究显示力量训练与死亡率相关",
        "每周三次力量训练者全因死亡率低 18%，效应在 60 岁以上人群中更明显。",
        "这类相关性研究的价值不在因果，而在于它把\"该练什么\"变成了可执行剂量。",
    ),
    (
        4.6,
        "环境气候",
        "欧洲多国遭遇异常暖秋，滑雪季开幕推迟",
        "法、德、奥三国 10 月均温偏高 3–5℃，低海拔雪场改用人工造雪或延后开业。",
        "单季异常说明不了趋势，但对靠雪吃饭的地区来说，这是连续第三年的现金流压力。",
    ),
    (
        3.4,
        "文化教育",
        "一所大学把期末论文的引用格式检查交给自动化工具",
        "校方称该工具只做格式提示、不参与评分，学生要求改为可选使用被驳回。",
        "争论表面是格式，实质是学校把训练成本转嫁给了学生。",
    ),
]


def build() -> str:
    items = []
    for idx, (score, category, title, summary, insight) in enumerate(SAMPLES, 1):
        items.append(
            Item(
                uid=f"demo{idx}",
                title=title,
                url="https://example.com/news/" + str(idx),
                source_id="demo",
                source_name=["中新网", "Reuters", "The Verge"][idx % 3],
                published=MOMENT,
                lead=summary,
                lang="zh",
                weight=1.0,
                score=score,
                category=category,
                reason="影响面广，且可能在两周内出现后续政策跟进",
                summary=summary,
                insight=insight,
                also_reported=["BBC 中文", "联合早报"] if idx == 1 else [],
            )
        )
    grouped = group_by_tier(items, DEFAULT_TIERS)
    return render_html(
        moment=MOMENT,
        overview="今天要看的只有三件事：中美重启经贸对话、美联储连续第二次降息、欧盟 AI 监管细则落地。其余都是余波。",
        grouped=grouped,
        stats={"feeds_ok": 16, "candidates": 137, "note": "本文件为版式样例"},
    )


if __name__ == "__main__":
    out = Path(__file__).resolve().parents[1] / "output" / "layout.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build(), encoding="utf-8")
    print(out)
