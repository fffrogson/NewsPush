# -*- coding: utf-8 -*-
"""Daily brief built on News Minimalist's own ranking.

No LLM, no ranking, no rewriting: the site already scores every story and
writes its summary. This module fetches that list, follows each story to its
page for the summary text, renders it and pushes it out.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from . import deliver, render
from .config import load as load_config
from .nm import Source, Story

__version__ = "0.2.0"
log = logging.getLogger("newsbrief.nm")


def _force_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001
            pass


def setup_logging(verbose: bool) -> None:
    _force_utf8()
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )


def day_line(stories: list[Story]) -> str:
    if not stories:
        return "今天没有达到阈值的重要新闻。"
    top = stories[0]
    head = f"今天最值得看的是「{top.title}」（{top.score:.1f} 分），共 {len(stories)} 条"
    rest = [s.title for s in stories[1:3]]
    if rest:
        head += "；其次是 " + "、".join(f"「{t}」" for t in rest)
    return head + "。"


def list_note(stories: list[Story]) -> str:
    if not stories:
        return "News Minimalist 今日无高于阈值的新闻。"
    analysed = max((s.analysed for s in stories), default=0)
    if analysed:
        return (
            f"News Minimalist 今日用 Gemini 读了 {analysed:,} 条新闻并给出重要性评分，"
            f"以下 {len(stories)} 条按分数从高到低排列。"
        )
    return f"以下 {len(stories)} 条按 News Minimalist 的重要性评分从高到低排列。"


def collect(cfg, limit: int | None = None) -> tuple[list[Story], dict]:
    nmcfg = cfg.section("nm") or {}
    min_score = float(nmcfg.get("min_score", 5.0))
    max_items = int(limit or nmcfg.get("max_items", 15))
    sort = str(nmcfg.get("sort", "significance"))
    fetch_summaries = bool(nmcfg.get("fetch_summaries", True))
    shards = int(nmcfg.get("sitemap_shards", 16))

    src = Source(nmcfg)
    try:
        stories = src.fetch_list(min_score=min_score, sort=sort)
        stories = [s for s in stories if s.score >= min_score][:max_items]
        stats = {"listed": len(stories), "matched": 0, "summaries": 0}

        if fetch_summaries and stories:
            stats["matched"] = src.map_stories(stories, shards=shards)
            for story in stories:
                if not story.nm_url:
                    continue
                src.fetch_article(story)
                if story.paragraphs:
                    stats["summaries"] += 1
    finally:
        src.close()
    return stories, stats


def main(argv: list[str] | None = None) -> int:
    _force_utf8()
    parser = argparse.ArgumentParser(
        prog="newsbrief", description="News Minimalist 每日要闻（仅转载，不重新打分）"
    )
    parser.add_argument("-c", "--config", default="config.yaml")
    parser.add_argument("--limit", type=int, default=None, help="最多取几条")
    parser.add_argument("--dry-run", action="store_true", help="只生成文件，不推送")
    parser.add_argument("--no-email", action="store_true")
    parser.add_argument("--no-bark", action="store_true")
    parser.add_argument("--out", default=None, help="输出目录（默认取配置）")
    parser.add_argument("--json", action="store_true", help="额外写出原始 JSON")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--version", action="version", version=f"newsbrief {__version__}")
    args = parser.parse_args(argv)

    setup_logging(args.verbose)

    cfg = load_config(args.config)
    tz = ZoneInfo(str(cfg.get("app.timezone") or cfg.get("timezone") or "Asia/Shanghai"))
    moment = datetime.now(tz)

    stories, stats = collect(cfg, limit=args.limit)
    if not stories:
        log.warning("没有取到任何新闻，可能是站点结构变化或网络不通")

    tiers = render.nm_tiers_from(cfg.section("nm") or {})
    grouped = render.nm_group(stories, tiers)
    line = day_line(stories)
    note = list_note(stories)

    outdir = Path(args.out or cfg.get("nm.output_dir") or "output")
    outdir.mkdir(parents=True, exist_ok=True)
    html_path = outdir / f"brief-{moment:%Y-%m-%d}.html"
    text_path = outdir / f"brief-{moment:%Y-%m-%d}.txt"

    html = render.render_nm_html(
        moment=moment, day_line=line, grouped=grouped, stats={"list_note": note}
    )
    text = render.render_nm_text(
        moment=moment, day_line=line, grouped=grouped, stats={"list_note": note}
    )
    html_path.write_text(html, encoding="utf-8")
    text_path.write_text(text, encoding="utf-8")
    log.info("写了 %s 与 %s", html_path, text_path)

    if args.json:
        raw_path = outdir / f"brief-{moment:%Y-%m-%d}.json"
        raw_path.write_text(
            json.dumps([s.to_dict() for s in stories], ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        log.info("写了 %s", raw_path)

    log.info(
        "入选 %d 条（列表 %d 条，匹配文章页 %d，取到摘要 %d）",
        len(stories),
        stats["listed"],
        stats["matched"],
        stats["summaries"],
    )

    if args.dry_run:
        log.info("dry-run：不推送")
        return 0

    delivery = cfg.section("delivery") or {}
    subject = f"今日要闻 · {moment:%m-%d} · {stories[0].score:.1f} 分起" if stories else "今日要闻"
    failures: list[str] = []
    attempted = 0

    if not args.no_email and (delivery.get("email") or {}).get("to"):
        attempted += 1
        try:
            deliver.send_email(delivery["email"], subject=subject, text=text, html=html)
            log.info("邮件已发送")
        except Exception as exc:  # noqa: BLE001
            failures.append(f"email: {exc}")
            log.error("邮件发送失败: %s", exc)

    if not args.no_bark and (delivery.get("bark") or {}).get("url"):
        attempted += 1
        try:
            title, body = render.render_nm_bark(moment=moment, day_line=line, grouped=grouped)
            deliver.send_bark(delivery["bark"], title=title, body=body)
            log.info("Bark 已推送")
        except Exception as exc:  # noqa: BLE001
            failures.append(f"bark: {exc}")
            log.error("Bark 推送失败: %s", exc)

    if failures:
        log.error("推送失败 %d/%d 个渠道: %s", len(failures), attempted, "; ".join(failures))
    return 1 if attempted and len(failures) >= attempted else 0
