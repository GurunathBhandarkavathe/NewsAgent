from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageStat

from newsagent.config import parse_rss_feeds
from newsagent.db import Database
from newsagent.pipeline import run_cycle, seconds_until_next_cycle

from helpers import make_config


def test_generated_slides_are_instagram_portrait_dimensions(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    db = Database(config.db_path)
    draft = run_cycle(config, db, use_mock=True)
    assert draft is not None

    for story in draft.stories:
        with Image.open(story.slide_path) as image:
            assert image.size == (1080, 1350)
            assert image.format == "JPEG"


def test_fallback_slide_visual_is_not_black(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    db = Database(config.db_path)
    draft = run_cycle(config, db, use_mock=True)
    assert draft is not None

    for story in draft.stories:
        with Image.open(story.slide_path) as image:
            top_visual = image.crop((0, 0, 1080, 890)).convert("L")
            assert ImageStat.Stat(top_visual).mean[0] > 90


def test_custom_rss_feed_parser_groups_urls_by_category() -> None:
    feeds = parse_rss_feeds(
        "politics=https://example.com/politics.xml;"
        "sports|https://example.com/sports.xml;"
        "https://example.com/fallback.xml"
    )

    assert feeds["politics"] == ["https://example.com/politics.xml"]
    assert feeds["sports"] == ["https://example.com/sports.xml"]
    assert feeds["current_affairs"] == ["https://example.com/fallback.xml"]


def test_seconds_until_next_cycle_returns_positive_wait() -> None:
    assert seconds_until_next_cycle("Asia/Kolkata", 3) > 0


def test_default_image_policy_is_branded_cards(tmp_path: Path) -> None:
    config = make_config(tmp_path)

    assert config.image_policy == "branded_cards"
    assert config.uses_article_images is False
