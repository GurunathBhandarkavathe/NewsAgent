from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from newsagent.briefs import description_detail, slide_brief
from newsagent.caption import PUBLISH_CAPTION_MAX_CHARS, build_caption
from newsagent.db import Database
from newsagent.models import DraftStory, NewsItem
from newsagent.pipeline import regenerate_draft_with_fresh_images, run_cycle
from newsagent.publisher import Publisher

from helpers import make_config


def test_mock_cycle_generates_carousel_draft(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    db = Database(config.db_path)

    draft = run_cycle(config, db, use_mock=True)

    assert draft is not None
    assert draft.status == "draft"
    assert 4 <= len(draft.stories) <= 5
    assert len(draft.stories) == 5
    assert {story.category for story in draft.stories} >= {
        "politics",
        "films",
        "sports",
        "current_affairs",
        "international",
    }
    for story in draft.stories:
        assert Path(story.slide_path).exists()
        assert Path(story.slide_path).stat().st_size > 0


def test_caption_has_expected_lines_sources_and_links(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    db = Database(config.db_path)

    draft = run_cycle(config, db, use_mock=True)
    assert draft is not None

    lines = [line for line in draft.caption.splitlines() if line.strip()]
    assert 18 <= len(lines) <= 24
    assert "Details:" in draft.caption
    assert "Mock summary for" in draft.caption
    assert "Source/courtesy:" in draft.caption
    assert "Sources/courtesy:" in draft.caption
    assert "Full report:" in draft.caption
    assert "https://example.com/" in draft.caption
    assert len(draft.caption) <= PUBLISH_CAPTION_MAX_CHARS


def test_caption_stays_under_instagram_publish_limit_with_long_news_details() -> None:
    stories = [
        DraftStory(
            key=f"story-{index}",
            title=f"Very long India news headline number {index} " + ("with extra context " * 10),
            url="https://example.com/news/" + ("very-long-path-segment-" * 8) + str(index),
            source="Example National News Source With Long Name",
            category="politics",
            published_at=None,
            summary=(
                "This update includes a detailed explanation of the issue, the people involved, "
                "the latest official response, and what readers should know next. "
            )
            * 5,
            image_url="",
            source_count=1,
            score=1.0,
        )
        for index in range(1, 6)
    ]

    caption = build_caption(stories)

    assert len(caption) <= PUBLISH_CAPTION_MAX_CHARS
    assert "Source/courtesy:" in caption
    assert "#SamacharBharat" in caption


def test_story_briefs_use_summary_context_instead_of_headline_only(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    db = Database(config.db_path)

    draft = run_cycle(config, db, use_mock=True)
    assert draft is not None
    story = draft.stories[0]

    assert "Mock summary for" in slide_brief(story)
    assert "Mock summary for" in description_detail(story)


def test_slide_brief_turns_headline_into_clear_news_sentence() -> None:
    story = DraftStory(
        key="story",
        title="Amid row over pellet use, CRPF chief’s ‘work fearlessly’ message to troops",
        url="https://example.com/story",
        source="Example",
        category="politics",
        published_at=None,
        summary="",
        image_url="",
        source_count=1,
        score=1.0,
    )

    brief = slide_brief(story)

    assert "message to troops amid row over pellet use" in brief
    assert brief.endswith(".")


def test_recent_duplicate_stories_are_skipped(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    db = Database(config.db_path)

    first = run_cycle(config, db, use_mock=True)
    second = run_cycle(config, db, use_mock=True)

    assert first is not None
    assert second is None


def test_approval_missing_meta_credentials_exports_manual_package(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    db = Database(config.db_path)
    draft = run_cycle(config, db, use_mock=True)
    assert draft is not None

    result = Publisher(config).publish(draft)

    assert result.status == "exported"
    export_path = Path(result.manual_export_path)
    assert export_path.exists()
    assert (export_path / "caption.txt").exists()
    assert (export_path / "sources.json").exists()


def test_cycle_does_not_publish_without_approval(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    db = Database(config.db_path)

    draft = run_cycle(config, db, use_mock=True)
    stored = db.get_draft(draft.id) if draft else None

    assert stored is not None
    assert stored.status == "draft"
    assert stored.published_at is None
    assert stored.publish_response == ""


def test_session_store_persists_drafts_as_json_without_sqlite(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    db = Database(config.db_path)

    draft = run_cycle(config, db, use_mock=True)

    assert draft is not None
    state = json.loads(Path(config.db_path).read_text(encoding="utf-8"))
    assert state["draft_order"] == [draft.id]
    assert state["drafts"][draft.id]["status"] == "draft"
    assert len(state["drafts"][draft.id]["stories"]) == 5
    assert len(state["seen_stories"]) == 5


def test_config_secrets_default_to_environment_only(tmp_path: Path) -> None:
    config = make_config(tmp_path)

    assert config.meta_access_token == ""
    assert config.instagram_business_account_id == ""
    assert config.public_asset_base_url == ""
    assert config.can_publish_to_meta is False


def test_real_cycle_requires_loadable_real_images(monkeypatch, tmp_path: Path) -> None:
    config = make_config(
        tmp_path,
        draft_min_items=4,
        draft_max_items=5,
        image_policy="article_images",
        require_real_images=True,
    )
    db = Database(config.db_path)
    items = [
        NewsItem("India parliament story", "https://example.com/politics", "Example", "politics", image_url="https://img.example/ok-politics.jpg"),
        NewsItem("Bollywood film story", "https://example.com/films", "Example", "films", image_url="https://img.example/ok-films.jpg"),
        NewsItem("India cricket story", "https://example.com/sports", "Example", "sports", image_url="https://img.example/ok-sports.jpg"),
        NewsItem(
            "Supreme Court policy story",
            "https://example.com/current",
            "Example",
            "current_affairs",
            image_url="https://img.example/ok-current.jpg",
        ),
        NewsItem("World India story", "https://example.com/world", "Example", "international", image_url="https://img.example/broken.jpg"),
        NewsItem("No image story", "https://example.com/no-image", "Example", "sports"),
    ]

    def fake_load_remote_image(url: str):
        if "ok-" not in url:
            return None
        return Image.new("RGB", (640, 420), (120, 180, 210))

    monkeypatch.setattr("newsagent.pipeline.collect_news", lambda cfg: (items, [{"adapter": "test", "status": "ok"}]))
    monkeypatch.setattr(
        "newsagent.pipeline.enrich_article_images",
        lambda story_items, limit: {"adapter": "article_image_enrichment", "status": "ok", "filled": 0},
    )
    monkeypatch.setattr("newsagent.pipeline.load_remote_image", fake_load_remote_image)
    monkeypatch.setattr("newsagent.image_render.load_remote_image", fake_load_remote_image)

    draft = run_cycle(config, db, use_mock=False)

    assert draft is not None
    assert len(draft.stories) == 4
    assert all(story.image_url and "ok-" in story.image_url for story in draft.stories)
    assert all(story.rights_risk == "reused_article_image_requires_manual_rights_review" for story in draft.stories)


def test_regenerate_images_replaces_draft_story_set(monkeypatch, tmp_path: Path) -> None:
    config = make_config(
        tmp_path,
        draft_min_items=4,
        draft_max_items=5,
        image_policy="article_images",
        require_real_images=True,
    )
    db = Database(config.db_path)
    original = run_cycle(config, db, use_mock=True)
    assert original is not None
    original_keys = {story.key for story in original.stories}

    items = [
        NewsItem("Fresh politics story", "https://example.com/fresh-politics", "Example", "politics", image_url="https://img.example/ok-1.jpg"),
        NewsItem("Fresh film story", "https://example.com/fresh-films", "Example", "films", image_url="https://img.example/ok-2.jpg"),
        NewsItem("Fresh sports story", "https://example.com/fresh-sports", "Example", "sports", image_url="https://img.example/ok-3.jpg"),
        NewsItem(
            "Fresh current affairs story",
            "https://example.com/fresh-current",
            "Example",
            "current_affairs",
            image_url="https://img.example/ok-4.jpg",
        ),
        NewsItem("Fresh world story", "https://example.com/fresh-world", "Example", "international", image_url="https://img.example/ok-5.jpg"),
    ]

    def fake_load_remote_image(url: str):
        return Image.new("RGB", (640, 420), (120, 180, 210))

    monkeypatch.setattr("newsagent.pipeline.collect_news", lambda cfg: (items, [{"adapter": "test", "status": "ok"}]))
    monkeypatch.setattr(
        "newsagent.pipeline.enrich_article_images",
        lambda story_items, limit: {"adapter": "article_image_enrichment", "status": "ok", "filled": 0},
    )
    monkeypatch.setattr("newsagent.pipeline.load_remote_image", fake_load_remote_image)
    monkeypatch.setattr("newsagent.image_render.load_remote_image", fake_load_remote_image)

    refreshed, refresh_log = regenerate_draft_with_fresh_images(config, db, original)
    stored = db.get_draft(original.id)

    assert refreshed is not None
    assert stored is not None
    assert {story.key for story in stored.stories}.isdisjoint(original_keys)
    assert [story.title for story in stored.stories] == [story.title for story in refreshed.stories]
    assert stored.caption.startswith("Samachar Bharat trend watch:")
    assert stored.log["image_regenerated_at"]
    assert refresh_log["fresh_count"] == 5


def test_branded_card_policy_does_not_fetch_or_render_article_images(monkeypatch, tmp_path: Path) -> None:
    config = make_config(tmp_path, draft_min_items=4, draft_max_items=5)
    db = Database(config.db_path)
    items = [
        NewsItem("India parliament story", "https://example.com/politics", "Example", "politics", image_url="https://img.example/politics.jpg"),
        NewsItem("Bollywood film story", "https://example.com/films", "Example", "films", image_url="https://img.example/films.jpg"),
        NewsItem("India cricket story", "https://example.com/sports", "Example", "sports", image_url="https://img.example/sports.jpg"),
        NewsItem("Supreme Court policy story", "https://example.com/current", "Example", "current_affairs", image_url="https://img.example/current.jpg"),
        NewsItem("World India story", "https://example.com/world", "Example", "international", image_url="https://img.example/world.jpg"),
    ]

    def fail_if_called(*args, **kwargs):
        raise AssertionError("branded_cards policy must not fetch or render article images")

    monkeypatch.setattr("newsagent.pipeline.collect_news", lambda cfg: (items, [{"adapter": "test", "status": "ok"}]))
    monkeypatch.setattr("newsagent.pipeline.enrich_article_images", fail_if_called)
    monkeypatch.setattr("newsagent.pipeline.load_remote_image", fail_if_called)
    monkeypatch.setattr("newsagent.image_render.load_remote_image", fail_if_called)

    draft = run_cycle(config, db, use_mock=False)

    assert draft is not None
    assert draft.log["image_policy"] == "branded_cards"
    assert all(story.rights_risk == "branded_card_no_external_news_image" for story in draft.stories)
