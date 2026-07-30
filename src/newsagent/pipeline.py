from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .caption import build_caption
from .config import Config
from .db import Database
from .image_render import load_remote_image, render_draft_images
from .models import Draft, DraftStory
from .scoring import cluster_items, score_items, select_balanced
from .sources import collect_news, enrich_article_images, mock_news_items
from .utils import isoformat, slugify, utcnow


def run_cycle(config: Config, db: Database | None = None, *, use_mock: bool = False) -> Draft | None:
    db = db or Database(config.db_path)
    started_at = utcnow()
    items, source_logs = (mock_news_items(started_at), [{"adapter": "mock", "status": "ok", "count": 6}]) if use_mock else collect_news(config)

    seen = db.recent_seen_keys(config.dedupe_hours)
    clustered = cluster_items(items)
    if not use_mock and config.uses_article_images:
        source_logs.append(enrich_article_images(clustered, limit=config.image_enrichment_limit))
    scored = score_items(clustered, now=started_at)
    fresh = [item for item in scored if item.key not in seen]
    image_ready_log = None
    if config.uses_article_images and config.require_real_images and not use_mock:
        fresh, image_ready_log = keep_items_with_loadable_images(fresh, config.image_enrichment_limit)
    skipped = [item for item in scored if item.key in seen]
    selected = select_balanced(fresh, min_items=config.draft_min_items, max_items=config.draft_max_items)

    log = {
        "started_at": isoformat(started_at),
        "brand": {"name": config.brand_name, "handle": config.brand_handle},
        "image_policy": config.image_policy,
        "source_logs": source_logs,
        "fetched_count": len(items),
        "clustered_count": len(clustered),
        "fresh_count": len(fresh),
        "skipped_duplicates": [{"title": item.title, "url": item.url} for item in skipped[:20]],
        "selected": [{"title": item.title, "category": item.category, "score": round(item.score, 2)} for item in selected],
    }
    if image_ready_log:
        log["image_ready"] = image_ready_log

    if len(selected) < config.draft_min_items:
        db.log_event("warning", "Not enough fresh stories to create a draft.", log)
        return None

    draft_id = make_draft_id(started_at)
    stories = [
        DraftStory(
            key=item.key,
            title=item.title,
            url=item.url,
            source=item.source,
            category=item.category,
            published_at=item.published_at,
            summary=item.summary,
            image_url=item.image_url,
            source_count=item.source_count,
            score=item.score,
        )
        for item in selected
    ]
    draft = Draft(
        id=draft_id,
        created_at=started_at,
        status="draft",
        stories=stories,
        caption=build_caption(
            stories,
            brand_name=config.brand_name,
            brand_handle=config.brand_handle,
            brand_tagline=config.brand_tagline,
        ),
        log=log,
    )

    render_draft_images(draft, config)
    write_draft_files(draft, config)
    db.save_draft(draft, mark_seen=True)
    db.log_event("info", "Created draft.", {"draft_id": draft.id, "story_count": len(draft.stories)})
    return draft


def regenerate_draft_with_fresh_images(config: Config, db: Database, draft: Draft) -> tuple[Draft | None, dict]:
    started_at = utcnow()
    items, source_logs = collect_news(config)
    current_keys = {story.key for story in draft.stories}
    seen = db.recent_seen_keys(config.dedupe_hours) | current_keys
    clustered = cluster_items(items)
    if config.uses_article_images:
        source_logs.append(enrich_article_images(clustered, limit=config.image_enrichment_limit))
    scored = score_items(clustered, now=started_at)
    fresh = [item for item in scored if item.key not in seen]
    image_ready_log = None
    if config.uses_article_images and config.require_real_images:
        fresh, image_ready_log = keep_items_with_loadable_images(fresh, config.image_enrichment_limit)
    selected = select_balanced(fresh, min_items=config.draft_min_items, max_items=config.draft_max_items)

    refresh_log = {
        "started_at": isoformat(started_at),
        "image_policy": config.image_policy,
        "source_logs": source_logs,
        "fetched_count": len(items),
        "clustered_count": len(clustered),
        "fresh_count": len(fresh),
        "previous_story_keys": sorted(current_keys),
        "selected": [{"title": item.title, "category": item.category, "score": round(item.score, 2)} for item in selected],
    }
    if image_ready_log:
        refresh_log["image_ready"] = image_ready_log

    if len(selected) < config.draft_min_items:
        return None, refresh_log

    stories = draft_stories_from_items(selected)
    draft.stories = stories
    draft.caption = build_caption(
        stories,
        variant=int(draft.log.get("caption_variant", 0)),
        brand_name=config.brand_name,
        brand_handle=config.brand_handle,
        brand_tagline=config.brand_tagline,
    )
    draft.status = "draft"
    draft.log["image_regenerated_at"] = isoformat(started_at)
    draft.log["image_regeneration"] = refresh_log
    draft.log["selected"] = refresh_log["selected"]

    render_draft_images(draft, config)
    write_draft_files(draft, config)
    db.replace_draft_stories(draft, mark_seen=True)
    db.update_draft(draft.id, status=draft.status, caption=draft.caption, log=draft.log)
    db.log_event(
        "info",
        "Draft images regenerated with fresh stories.",
        {"draft_id": draft.id, "story_count": len(draft.stories)},
    )
    return draft, refresh_log


def write_draft_files(draft: Draft, config: Config) -> None:
    draft_dir = config.assets_dir / "drafts" / draft.id
    draft_dir.mkdir(parents=True, exist_ok=True)
    (draft_dir / "caption.txt").write_text(draft.caption, encoding="utf-8")
    (draft_dir / "sources.json").write_text(
        json.dumps(
            [
                {
                    "title": story.title,
                    "url": story.url,
                    "source": story.source,
                    "category": story.category,
                    "slide_path": story.slide_path,
                    "rights_risk": story.rights_risk,
                    "score": story.score,
                }
                for story in draft.stories
            ],
            indent=2,
        ),
        encoding="utf-8",
    )
    (draft_dir / "cycle-log.json").write_text(json.dumps(draft.log, indent=2), encoding="utf-8")


def draft_stories_from_items(items) -> list[DraftStory]:
    return [
        DraftStory(
            key=item.key,
            title=item.title,
            url=item.url,
            source=item.source,
            category=item.category,
            published_at=item.published_at,
            summary=item.summary,
            image_url=item.image_url,
            source_count=item.source_count,
            score=item.score,
        )
        for item in items
    ]


def keep_items_with_loadable_images(items, limit: int) -> tuple[list, dict]:
    ready = []
    checked = 0
    skipped_without_url = 0
    skipped_unloadable = 0
    for item in items:
        if not item.image_url:
            skipped_without_url += 1
            continue
        if checked >= limit:
            break
        checked += 1
        if load_remote_image(item.image_url):
            ready.append(item)
        else:
            skipped_unloadable += 1
    return ready, {
        "required": True,
        "checked": checked,
        "ready": len(ready),
        "skipped_without_url": skipped_without_url,
        "skipped_unloadable": skipped_unloadable,
    }


def make_draft_id(created_at: datetime) -> str:
    stamp = created_at.strftime("%Y%m%d-%H%M%S")
    return f"{stamp}-{slugify(str(created_at.timestamp()).replace('.', '-'), 'draft')}"


def seconds_until_next_cycle(timezone_name: str, cycle_hours: int) -> int:
    zone = ZoneInfo(timezone_name)
    now = datetime.now(zone)
    base = now.replace(minute=0, second=0, microsecond=0)
    next_hour = ((now.hour // cycle_hours) + 1) * cycle_hours
    days = 0
    if next_hour >= 24:
        next_hour -= 24
        days = 1
    next_run = base.replace(hour=next_hour) + timedelta(days=days)
    return max(1, int((next_run - now).total_seconds()))


def worker_loop(config: Config, *, use_mock: bool = False, immediate: bool = False) -> None:
    db = Database(config.db_path)
    if immediate:
        run_cycle(config, db, use_mock=use_mock)
    while True:
        sleep_for = seconds_until_next_cycle(config.timezone, config.cycle_hours)
        db.log_event("info", "Worker sleeping until next cycle.", {"seconds": sleep_for})
        time.sleep(sleep_for)
        run_cycle(config, db, use_mock=use_mock)
