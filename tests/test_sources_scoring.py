from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

from newsagent.models import NewsItem
from newsagent.scoring import cluster_items, score_items, select_balanced
from newsagent.sources import (
    GoogleTrendsAdapter,
    RSSAdapter,
    collect_news,
    enrich_article_details,
    enrich_article_images,
    extract_article_image,
    extract_article_metadata,
)
from newsagent.utils import utcnow

from helpers import make_config


class FakeHTTPResponse:
    def __init__(self, text: str, content_type: str = "text/html"):
        self.text = text
        self.headers = {"content-type": content_type}

    def raise_for_status(self) -> None:
        return None


def test_rss_adapter_parses_items_and_extracts_summary_image(monkeypatch) -> None:
    parsed_feed = SimpleNamespace(
        feed={"title": "Example Feed"},
        entries=[
            {
                "title": "India cricket team announces squad",
                "link": "https://example.com/story?utm_source=feed",
                "summary": '<p>Short update</p><img src="https://example.com/image.jpg">',
                "published": "Thu, 30 Jul 2026 06:00:00 GMT",
            }
        ],
    )
    monkeypatch.setattr("newsagent.sources.feedparser.parse", lambda *args, **kwargs: parsed_feed)

    items = RSSAdapter({"sports": ["https://feed.example/rss"]}).fetch()

    assert len(items) == 1
    assert items[0].category == "sports"
    assert items[0].source == "Example Feed"
    assert items[0].summary == "Short update"
    assert items[0].image_url == "https://example.com/image.jpg"
    assert items[0].url == "https://example.com/story"


def test_extract_article_image_uses_open_graph_metadata(monkeypatch) -> None:
    html = """
    <html>
      <head>
        <meta property="og:image" content="/photos/news-image.jpg">
        <meta name="description" content="This is a useful source-written context line for the article.">
      </head>
      <body><img src="/logo.png"></body>
    </html>
    """
    monkeypatch.setattr("newsagent.sources.requests.get", lambda *args, **kwargs: FakeHTTPResponse(html))

    image_url = extract_article_image("https://news.example/story")
    metadata = extract_article_metadata("https://news.example/story")

    assert image_url == "https://news.example/photos/news-image.jpg"
    assert metadata["description"] == "This is a useful source-written context line for the article."


def test_extract_article_metadata_collects_article_body_context(monkeypatch) -> None:
    html = """
    <html>
      <head>
        <meta name="description" content="Short source summary for the story.">
      </head>
      <body>
        <nav>This should not appear.</nav>
        <article>
          <p>Officials said the decision was taken after a review meeting with state representatives and sector experts.</p>
          <p>The report added that the next phase will include public consultations, implementation timelines and follow-up notices.</p>
          <p>Advertisement</p>
        </article>
      </body>
    </html>
    """
    monkeypatch.setattr("newsagent.sources.requests.get", lambda *args, **kwargs: FakeHTTPResponse(html))

    metadata = extract_article_metadata("https://news.example/story")

    assert "review meeting with state representatives" in metadata["article_text"]
    assert "public consultations" in metadata["article_text"]
    assert "Advertisement" not in metadata["article_text"]


def test_article_detail_enrichment_prefers_richer_article_context(monkeypatch) -> None:
    html = """
    <html>
      <body>
        <article>
          <p>Officials said the move follows weeks of talks and will change how the programme is implemented across states.</p>
          <p>The article said departments will publish a timeline, clarify eligibility and issue district-level instructions next week.</p>
        </article>
      </body>
    </html>
    """
    item = NewsItem("India policy update", "https://news.example/story", "Example", "politics", summary="Short update")
    monkeypatch.setattr("newsagent.sources.requests.get", lambda *args, **kwargs: FakeHTTPResponse(html))

    log = enrich_article_details([item])

    assert log["enriched"] == 1
    assert "weeks of talks" in item.summary
    assert "district-level instructions" in item.summary


def test_article_enrichment_fills_missing_summary_from_metadata(monkeypatch) -> None:
    html = """
    <html>
      <head>
        <meta property="og:image" content="https://news.example/photo.jpg">
        <meta property="og:description" content="Officials said the decision follows a review meeting and will affect the next phase of the policy rollout.">
      </head>
    </html>
    """
    item = NewsItem("India policy update", "https://news.example/story", "Example", "politics", summary="")
    monkeypatch.setattr("newsagent.sources.requests.get", lambda *args, **kwargs: FakeHTTPResponse(html))

    log = enrich_article_images([item])

    assert log["filled"] == 1
    assert log["summary_filled"] == 1
    assert item.image_url == "https://news.example/photo.jpg"
    assert item.summary.startswith("Officials said")


def test_extract_article_image_ignores_google_news_wrapper(monkeypatch) -> None:
    def fail_if_called(*args, **kwargs):
        raise AssertionError("wrapper pages should not be fetched for images")

    monkeypatch.setattr("newsagent.sources.requests.get", fail_if_called)

    image_url = extract_article_image("https://news.google.com/rss/articles/example?oc=5")

    assert image_url == ""


def test_google_trends_adapter_guesses_category_from_trend_text(monkeypatch) -> None:
    parsed_feed = SimpleNamespace(
        feed={"title": "Google Trends"},
        entries=[
            {
                "title": "Bollywood box office record",
                "link": "https://trends.example/bollywood",
                "summary": "Indian cinema searches rise fast",
            }
        ],
    )
    monkeypatch.setattr("newsagent.sources.feedparser.parse", lambda *args, **kwargs: parsed_feed)

    items = GoogleTrendsAdapter("https://trends.example/rss").fetch()

    assert items[0].source == "Google Trends India"
    assert items[0].category == "films"
    assert "google_trends" in items[0].adapters


def test_collect_news_logs_adapter_failures(monkeypatch, tmp_path: Path) -> None:
    config = make_config(tmp_path, enable_rss=True, rss_feeds={"sports": ["https://feed.example/rss"]})

    def failing_parse(*args, **kwargs):
        raise RuntimeError("feed unavailable")

    monkeypatch.setattr("newsagent.sources.feedparser.parse", failing_parse)

    items, logs = collect_news(config)

    assert items == []
    assert logs == [{"adapter": "rss", "status": "error", "error": "feed unavailable"}]


def test_scoring_clusters_same_story_and_selects_balanced_categories() -> None:
    now = utcnow()
    items = [
        NewsItem(
            title="India cricket team announces squad",
            url="https://one.example/cricket",
            source="One",
            category="sports",
            published_at=now,
            image_url="https://one.example/img.jpg",
            adapters=["rss"],
        ),
        NewsItem(
            title="India cricket team announces squad",
            url="https://two.example/cricket",
            source="Two",
            category="sports",
            published_at=now - timedelta(minutes=5),
            adapters=["gdelt"],
        ),
        NewsItem("India parliament debates bill", "https://example.com/politics", "Example", "politics", now),
        NewsItem("Bollywood film breaks record", "https://example.com/films", "Example", "films", now),
        NewsItem("Supreme Court hears policy case", "https://example.com/current", "Example", "current_affairs", now),
        NewsItem("India raises global issue at UN", "https://example.com/world", "Example", "international", now),
    ]

    clustered = cluster_items(items)
    scored = score_items(clustered, now=now)
    selected = select_balanced(scored, min_items=4, max_items=5)

    sports = [item for item in clustered if item.category == "sports"]
    assert len(sports) == 1
    assert sports[0].source_count == 2
    assert sports[0].image_url == "https://one.example/img.jpg"
    assert {item.category for item in selected} == {
        "politics",
        "films",
        "sports",
        "current_affairs",
        "international",
    }
