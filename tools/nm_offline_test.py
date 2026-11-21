# -*- coding: utf-8 -*-
"""Offline checks for the News Minimalist pipeline.

No network, no browser: every test feeds a canned payload through the same
code the daily job runs. ``python tools/nm_offline_test.py`` exits 0 on pass.
"""

from __future__ import annotations

import html as html_lib
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from newsbrief import render  # noqa: E402
from newsbrief.nm import Source, Story, parse_meta, parse_score, slugify  # noqa: E402
from newsbrief.nm_main import day_line, list_note  # noqa: E402

FAILS: list[str] = []
CHECKS = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global CHECKS
    CHECKS += 1
    if not cond:
        FAILS.append(f"{name}{(' — ' + detail) if detail else ''}")


def stories_from_fixture() -> list[Story]:
    rows = json.loads((ROOT / "tools" / "fixture_nm.json").read_text(encoding="utf-8"))
    out = []
    for row in rows:
        out.append(
            Story(
                score=float(row["score"]),
                title=row["title"],
                nm_url=row.get("nm_url", ""),
                source_url=row.get("source_url", ""),
                domain=row.get("domain", ""),
                related=int(row.get("related", 0)),
                age=row.get("age", ""),
                published=row.get("published", ""),
                paragraphs=list(row.get("paragraphs", [])),
                rank_pct=row.get("rank_pct", ""),
                analysed=int(row.get("analysed", 0)),
            )
        )
    return out


def test_helpers() -> None:
    check("score 解析", parse_score("[6.6]") == 6.6, str(parse_score("[6.6]")))
    check("score 空值", parse_score("") == 0.0)
    check("meta 带来源数", parse_meta("(bbc.com + 49)") == ("bbc.com", 49))
    check("meta 无来源数", parse_meta("(npr.org)") == ("npr.org", 0))
    check("slug 去标点", slugify("Trump's $7.25 Billion Deal!") == "trump-s-7-25-billion-deal")
    check("slug 弯引号", slugify("Israel\u2019s plan") == "israel-s-plan")


def test_fixture_shape(stories: list[Story]) -> None:
    check("fixture 非空", len(stories) >= 5, f"{len(stories)} 条")
    check("按分数降序", [s.score for s in stories] == sorted((s.score for s in stories), reverse=True))
    check("每条有原文链接", all(s.source_url.startswith("http") for s in stories))
    check("每条有文章页", all(s.nm_url.startswith("http") for s in stories))
    check("每条有摘要段落", all(len(s.paragraphs) >= 1 for s in stories))
    check("摘要不是标题复读", all(s.paragraphs[0].strip() != s.title.strip() for s in stories))


def test_article_parser() -> None:
    story = Story(score=5.5, title="Sample headline about a treaty")
    text = "\n".join(
        [
            "Sample headline about a treaty",
            "ilsole24ore.com (Italian) — November 21, 2026 at 08:02 AM GMT+8",
            "",
            "The two sides signed a treaty on Tuesday, ending a decade of talks between them.",
            "",
            "Officials said the deal covers tariffs on 87 categories of goods.",
            "",
            "Share",
            "",
            "With a significance score of 5.5, this news ranks in the top 1% of today's 31530 analyzed articles.",
            "",
            "Most significant articles on this story:",
            "[5.7]",
            "A shorter version of the same headline (bbc.com)",
        ]
    )
    Source._parse_article(story, text)
    check("解析出段落", len(story.paragraphs) == 2, str(len(story.paragraphs)))
    check("段落不含 Share", all("Share" not in p for p in story.paragraphs))
    check("解析出百分位", story.rank_pct == "1", story.rank_pct)
    check("解析出样本量", story.analysed == 31530, str(story.analysed))
    check("解析出时间", "November 21, 2026" in story.published, story.published)


def test_matching() -> None:
    stories = [
        Story(score=6.0, title="Kremlin stages nuclear briefcase display"),
        Story(score=5.5, title="A completely unrelated headline about farming"),
    ]
    mapping = {
        "kremlin-stages-nuclear-briefcase-display": "https://nm/a",
        "kremlin-stages-nuclear-briefcase-display-to-threaten-ukraines-allies": "https://nm/b",
    }
    hits = Source.match_titles(stories, mapping)
    check("精确 slug 命中", stories[0].nm_url.startswith("http"), stories[0].nm_url)
    check("无关条目不误配", stories[1].nm_url == "", stories[1].nm_url)
    check("命中计数", hits == 1, str(hits))


def test_render(stories: list[Story]) -> None:
    tiers = render.nm_tiers_from({})
    grouped = render.nm_group(stories, tiers)
    check("分档非空", len(grouped) >= 1)
    check("分档总数等于条数", sum(len(i) for _, i in grouped) == len(stories))
    check("档内降序", all(
        [s.score for s in items] == sorted((s.score for s in items), reverse=True)
        for _, items in grouped
    ))
    check("低于最低档的被丢弃", all(s.score >= tiers[-1]["min"] for _, i in grouped for s in i))

    moment = datetime(2026, 11, 21, 7, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    line = day_line(stories)
    note = list_note(stories)
    html = render.render_nm_html(moment=moment, day_line=line, grouped=grouped, stats={"list_note": note})
    text = render.render_nm_text(moment=moment, day_line=line, grouped=grouped, stats={"list_note": note})
    title, body = render.render_nm_bark(moment=moment, day_line=line, grouped=grouped)

    check("html 含全部标题", all(html_lib.escape(s.title, quote=True) in html for s in stories))
    check("html 含原文链接", all(s.source_url in html for s in stories))
    check("html 有分段", html.count("<p style=\"margin:10px 0 0") >= len(stories))
    check("text 含链接", all(s.source_url in text for s in stories))
    check("bark 标题非空", bool(title))
    check("bark 体积", len(body.encode("utf-8")) < 4000, str(len(body.encode("utf-8"))))
    check("bark 提到分数", "（" in body and "）" in body)
    check("页脚注明转载", "News Minimalist 生成" in html)


def main() -> int:
    stories = stories_from_fixture()
    test_helpers()
    test_fixture_shape(stories)
    test_article_parser()
    test_matching()
    test_render(stories)

    if FAILS:
        print(f"FAILED {len(FAILS)}/{CHECKS}")
        for line in FAILS:
            print("  ✗", line)
        return 1
    print(f"OK {CHECKS} checks")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
