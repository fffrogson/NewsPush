# -*- coding: utf-8 -*-
"""Entry point: fetch → rank → summarise → render → deliver."""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from . import __version__
from .cluster import cluster
from .config import load
from .deliver import send_bark, send_email
from .extract import fill_bodies
from .fetch import fetch_all
from .llm import ChatClient, LLMError
from .models import Item
from .rank import (
    dedupe_by_topic,
    drop_echo_summaries,
    make_overview,
    recalibrate,
    score_items,
    summarize_items,
)
from .render import (
    group_by_tier,
    render_bark_digest,
    render_bark_parts,
    render_html,
    render_text,
    tiers_from,
)

log = logging.getLogger("newsbrief")

PREVIEW_NOTE = "预览模式：未调用 AI，标题与导语为原文，未做重要性排序与摘要生成。"


def _force_utf8() -> None:
    """Windows consoles default to GBK; Chinese logs turn to mojibake without this."""
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


def setup_logging(verbose: bool) -> None:
    _force_utf8()
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )


def cap_per_source(items: list[Item], cap: int) -> list[Item]:
    if cap <= 0:
        return items
    buckets: dict[str, list[Item]] = {}
    for item in items:
        buckets.setdefault(item.source_id, []).append(item)
    kept: list[Item] = []
    for group in buckets.values():
        group.sort(key=lambda it: it.published, reverse=True)
        kept.extend(group[:cap])
    kept.sort(key=lambda it: it.published, reverse=True)
    return kept


def select(items: list[Item], min_score: float, max_items: int, zh_min: int = 0) -> list[Item]:
    """Top stories by score, with a floor on how many come from Chinese sources."""
    ranked = sorted((it for it in items if it.score >= min_score), key=lambda it: it.score, reverse=True)
    picked = ranked[:max_items]

    if zh_min > 0:
        have = sum(1 for it in picked if it.lang == "zh")
        if have < zh_min:
            taken = {id(it) for it in picked}
            spare = [it for it in ranked if it.lang == "zh" and id(it) not in taken]
            for cand in spare[: zh_min - have]:
                foreign = [it for it in picked if it.lang != "zh"]
                if not foreign:
                    break
                picked.remove(min(foreign, key=lambda it: it.score))
                picked.append(cand)
            picked.sort(key=lambda it: it.score, reverse=True)

    return picked


def preview_scores(items: list[Item], limit: int) -> None:
    """Fill placeholder values so the layout can be inspected without an API key."""
    for item in items[:limit]:
        item.score = 5.0
        item.summary = item.lead[:260] or item.title
        item.insight = "（预览模式未生成解读）"


def _load_brief(path: str) -> tuple[list[Item], str, dict | None]:
    """Rebuild Items from a previously written brief-*.json so it can be resent."""
    import json as _json

    data = _json.loads(Path(path).read_text(encoding="utf-8"))
    items: list[Item] = []
    for row in data.get("items", []):
        try:
            published = datetime.fromisoformat(str(row.get("published") or ""))
        except ValueError:
            published = datetime.now()
        item = Item(
            uid=str(row.get("url") or row.get("title") or ""),
            title=str(row.get("title") or ""),
            url=str(row.get("url") or ""),
            source_id=str(row.get("source") or ""),
            source_name=str(row.get("source") or ""),
            published=published,
            lead="",
            lang=str(row.get("lang") or ""),
        )
        item.score = float(row.get("score") or 0)
        item.title_zh = str(row.get("title_zh") or "")
        item.summary = str(row.get("summary") or "")
        item.insight = str(row.get("insight") or "")
        item.terms = list(row.get("terms") or [])
        item.category = str(row.get("category") or "")
        item.reason = str(row.get("reason") or "")
        items.append(item)
    return items, str(data.get("overview") or ""), data.get("usage")


def main(argv: list[str] | None = None) -> int:
    _force_utf8()
    parser = argparse.ArgumentParser(prog="newsbrief", description="每日世界要闻简报")
    parser.add_argument("-c", "--config", default="config.yaml", help="配置文件路径")
    parser.add_argument("--preview", action="store_true", help="不调用 AI，仅抓取并渲染版式")
    parser.add_argument("--dry-run", action="store_true", help="不发送邮件/Bark")
    parser.add_argument("--no-email", action="store_true")
    parser.add_argument("--no-bark", action="store_true")
    parser.add_argument("--out", default="output", help="产物输出目录")
    parser.add_argument("--json", action="store_true", help="同时写出 JSON")
    parser.add_argument("--limit", type=int, default=0, help="覆盖 config 里的 max_items")
    parser.add_argument(
        "--resend", metavar="BRIEF.json", help="不抓取不调 AI，直接从已生成的 JSON 重发"
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--version", action="version", version=f"newsbrief {__version__}")
    args = parser.parse_args(argv)

    setup_logging(args.verbose)

    cfg = load(args.config)
    tz = ZoneInfo(cfg.get("timezone", "Asia/Shanghai"))
    now = datetime.now(tz)
    log.info("=== 每日要闻 %s ===", now.strftime("%Y-%m-%d %H:%M %Z"))

    tiers = tiers_from(cfg.data)
    max_items = int(cfg.get("max_items", 20))
    if args.limit:
        max_items = args.limit

    if args.resend:
        chosen, overview, usage_info = _load_brief(args.resend)
        feeds_ok = 0
        merged = chosen
        log.info("重发模式：从 %s 读取 %d 条，跳过抓取与 AI", args.resend, len(chosen))
    else:
        feeds = cfg.feeds
        log.info("开始抓取 %d 个 RSS 源", len(feeds))
        raw, stats = fetch_all(
            feeds,
            timeout=int(cfg.get("fetch.timeout", 20)),
            workers=int(cfg.get("fetch.workers", 10)),
            allow_undated=bool(cfg.get("fetch.allow_undated", False)),
            max_entries=int(cfg.get("fetch.max_entries", 60)),
        )
        feeds_ok = sum(1 for s in stats if s.ok)
        log.info("抓取完成：%d 条原始条目，%d/%d 个源可用", len(raw), feeds_ok, len(feeds))

        window = int(cfg.get("window_hours", 26))
        cutoff = now - timedelta(hours=window)
        fresh = [it for it in raw if it.published >= cutoff]
        log.info("时间窗 %dh 内 %d 条", window, len(fresh))

        fresh = cap_per_source(fresh, int(cfg.get("per_source_cap", 15)))
        merged = cluster(fresh, threshold=float(cfg.get("cluster_threshold", 0.45)))
        log.info("跨源去重后 %d 条独立事件", len(merged))

        max_candidates = int(cfg.get("max_candidates", 120))
        candidates = merged[:max_candidates]
        log.info("送入评估 %d 条", len(candidates))

        if args.preview:
            log.info("预览模式：跳过 AI 打分与摘要")
            preview_scores(candidates, max_items)
            chosen = candidates[:max_items]
            overview = ""
            usage_info = None
        else:
            try:
                client = ChatClient(cfg.section("ai"))
            except LLMError as exc:
                log.error("无法初始化 LLM: %s", exc)
                return 2

            score_items(client, candidates, cfg.section("scoring"))
            if cfg.get("scoring.recalibrate", True):
                recalibrate(client, candidates, cfg.section("scoring"))

            floor = min((t["min"] for t in tiers), default=3.5)
            zh_min = int(cfg.get("balance.zh_min", 0))

            # Pick a wider shortlist first: merging duplicates inside the final list
            # is what actually removes repeats from the reader's view, and it needs
            # spare items to refill from afterwards.
            wide = select(candidates, floor, int(max_items * 1.8) + 3, zh_min)
            wide = dedupe_by_topic(client, wide, cfg.section("dedupe"))
            chosen = select(wide, floor, max_items, zh_min)
            log.info("入选 %d 条（阈值 %.1f 分）", len(chosen), floor)

            fill_bodies(chosen, cfg.section("extraction"))
            summarize_items(client, chosen, cfg.section("summarising"))
            drop_echo_summaries(chosen)
            overview = make_overview(client, chosen)
            usage = client.usage_summary()
            usage_info = usage
            log.info(
                "token 用量：%d 次调用，输入 %d（缓存命中 %d），输出 %d，合计 %d",
                usage["calls"],
                usage["prompt_tokens"],
                usage["cached_tokens"],
                usage["completion_tokens"],
                usage["total_tokens"],
            )

    grouped = group_by_tier(chosen, tiers)

    stats_dict = {
        "feeds_ok": feeds_ok,
        "candidates": len(merged),
        "note": PREVIEW_NOTE if args.preview else "",
    }
    html_out = render_html(moment=now, overview=overview, grouped=grouped, stats=stats_dict)
    text_out = render_text(moment=now, overview=overview, grouped=grouped, stats=stats_dict)
    bark_max = int(cfg.get("delivery.bark.max_bytes", 3400))
    # One notification is the default: a stacked pile of 6 pushes reads in reverse
    # order on the lock screen, which makes the ranking look scrambled.
    if cfg.get("delivery.bark.split", False):
        bark_parts = render_bark_parts(moment=now, overview=overview, grouped=grouped, max_bytes=bark_max)
    else:
        bark_parts = [render_bark_digest(moment=now, overview=overview, grouped=grouped, max_bytes=bark_max)]

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = now.strftime("%Y-%m-%d")
    html_path = out_dir / f"brief-{stamp}.html"
    text_path = out_dir / f"brief-{stamp}.txt"
    html_path.write_text(html_out, encoding="utf-8")
    text_path.write_text(text_out, encoding="utf-8")
    log.info("已写出版式：%s", html_path)

    if args.json:
        import json as _json

        payload = {
            "generated_at": now.isoformat(),
            "overview": overview,
            "usage": usage_info,
            "items": [
                {
                    "score": it.score,
                    "title_zh": it.title_zh,
                    "title": it.title,
                    "summary": it.summary,
                    "insight": it.insight,
                    "terms": it.terms,
                    "category": it.category,
                    "reason": it.reason,
                    "source": it.source_name,
                    "url": it.url,
                    "lang": it.lang,
                    "published": it.published.isoformat(),
                }
                for it in chosen
            ],
        }
        json_path = out_dir / f"brief-{stamp}.json"
        json_path.write_text(_json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        log.info("已写出 JSON：%s", json_path)

    if args.dry_run or args.preview:
        log.info("跳过发送（dry-run/preview）")
        print("\n" + text_out[:1500])
        return 0

    subject = f"今日要闻 · {now.strftime('%m-%d')} · {len(chosen)} 条"
    failures: list[str] = []
    attempted = 0

    if not args.no_email and cfg.get("delivery.email.enabled", False):
        attempted += 1
        try:
            send_email(cfg.section("delivery.email"), subject=subject, text=text_out, html=html_out)
            log.info("邮件已发送：%s", cfg.get("delivery.email.to", ""))
        except Exception as exc:  # noqa: BLE001
            log.error("邮件发送失败: %s", exc)
            failures.append(f"email: {exc}")
    else:
        log.info("邮件：未启用或已跳过")

    if not args.no_bark and cfg.get("delivery.bark.enabled", False):
        attempted += 1
        bark_cfg = cfg.section("delivery.bark")
        try:
            parts = bark_parts
            use_md = bool(cfg.get("delivery.bark.markdown", True))
            interval = float(cfg.get("delivery.bark.interval", 8) or 0)
            # iOS shows the newest notification on top. To make the lock screen read
            # 1→15 from top to bottom, the LAST push must be the one holding item 1,
            # so we send the tail first and wait a beat between pushes.
            order = list(range(len(parts)))
            if bool(cfg.get("delivery.bark.reverse", True)):
                order.reverse()
            for pos, idx in enumerate(order):
                part_title, part_md, part_plain = parts[idx]
                final = pos == len(order) - 1
                send_bark(
                    bark_cfg,
                    title=part_title,
                    body=part_plain,
                    markdown=part_md if use_md else None,
                    sound=None if final else "none",
                    level=None if final else "passive",
                )
                if not final and interval:
                    time.sleep(interval)
            log.info("Bark 已推送 %d 条", len(parts))
        except Exception as exc:  # noqa: BLE001
            log.error("Bark 推送失败: %s", exc)
            failures.append(f"bark: {exc}")
    else:
        log.info("Bark：未启用或已跳过")

    if failures and len(failures) == attempted:
        log.error("所有推送渠道都失败了，本次简报未送达")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
