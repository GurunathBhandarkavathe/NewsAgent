from __future__ import annotations

import json
from datetime import timedelta
from typing import Iterable
from urllib.parse import urljoin, urlparse

import feedparser
import requests
from bs4 import BeautifulSoup

from .config import Config
from .models import NewsItem
from .utils import clean_text, parse_datetime, source_from_url, truncate_words, utcnow


USER_AGENT = "NewsAgent/0.1 (+local approval workflow)"
IMAGE_META_KEYS = (
    ("property", "og:image:secure_url"),
    ("property", "og:image:url"),
    ("property", "og:image"),
    ("name", "twitter:image:src"),
    ("name", "twitter:image"),
)
DESCRIPTION_META_KEYS = (
    ("property", "og:description"),
    ("name", "twitter:description"),
    ("name", "description"),
)
IMAGE_ATTRS = ("src", "data-src", "data-original", "data-lazy-src")


CATEGORY_KEYWORDS = {
    "politics": {
        "election",
        "parliament",
        "government",
        "minister",
        "modi",
        "bjp",
        "congress",
        "cabinet",
        "assembly",
        "lok sabha",
        "rajya sabha",
    },
    "films": {
        "bollywood",
        "film",
        "movie",
        "cinema",
        "actor",
        "actress",
        "box office",
        "ott",
        "trailer",
        "song",
    },
    "sports": {
        "cricket",
        "ipl",
        "match",
        "series",
        "football",
        "hockey",
        "olympic",
        "tennis",
        "badminton",
        "score",
    },
    "international": {
        "world",
        "global",
        "us",
        "china",
        "russia",
        "uk",
        "pakistan",
        "israel",
        "gaza",
        "europe",
        "united nations",
    },
}


class SourceAdapter:
    name = "source"

    def fetch(self) -> list[NewsItem]:
        raise NotImplementedError


class RSSAdapter(SourceAdapter):
    name = "rss"

    def __init__(self, feeds: dict[str, list[str]], timeout: int = 15):
        self.feeds = feeds
        self.timeout = timeout

    def fetch(self) -> list[NewsItem]:
        items: list[NewsItem] = []
        for category, urls in self.feeds.items():
            for url in urls:
                parsed = feedparser.parse(url, request_headers={"User-Agent": USER_AGENT})
                feed_source = clean_text(parsed.feed.get("title", "")) or source_from_url(url)
                for entry in parsed.entries[:25]:
                    title = clean_text(entry.get("title", ""))
                    link = entry.get("link", "")
                    if not title or not link:
                        continue
                    summary = clean_text(entry.get("summary", "") or entry.get("description", ""))
                    entry_source = entry.get("source", {}) or {}
                    source = clean_text(entry_source.get("title", "")) if isinstance(entry_source, dict) else ""
                    items.append(
                        NewsItem(
                            title=title,
                            url=link,
                            source=source or publisher_source(feed_source, link, url),
                            category=category,
                            published_at=parse_datetime(entry.get("published_parsed") or entry.get("updated_parsed")),
                            summary=summary,
                            image_url=self._entry_image(entry),
                            adapters=[self.name],
                        )
                    )
        return items

    @staticmethod
    def _entry_image(entry: dict) -> str:
        for key in ("media_content", "media_thumbnail"):
            for media in entry.get(key, []) or []:
                url = media.get("url")
                if url:
                    return url
        for enclosure in entry.get("enclosures", []) or []:
            href = enclosure.get("href")
            mime = enclosure.get("type", "")
            if href and ("image" in mime or href.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))):
                return href
        summary = entry.get("summary", "") or entry.get("description", "")
        if summary:
            soup = BeautifulSoup(summary, "html.parser")
            img = soup.find("img")
            if img and img.get("src"):
                return img["src"]
        return ""


class GoogleTrendsAdapter(RSSAdapter):
    name = "google_trends"

    def __init__(self, url: str):
        super().__init__({"current_affairs": [url]})

    def fetch(self) -> list[NewsItem]:
        items = super().fetch()
        for item in items:
            item.source = "Google Trends India"
            item.category = guess_category(f"{item.title} {item.summary}")
            if self.name not in item.adapters:
                item.adapters.append(self.name)
        return items


class GDELTAdapter(SourceAdapter):
    name = "gdelt"
    endpoint = "https://api.gdeltproject.org/api/v2/doc/doc"

    def __init__(self, categories: Iterable[str], timespan_hours: int = 6, timeout: int = 20):
        self.categories = list(categories)
        self.timespan_hours = timespan_hours
        self.timeout = timeout

    def fetch(self) -> list[NewsItem]:
        items: list[NewsItem] = []
        for category in self.categories:
            params = {
                "query": self._query_for_category(category),
                "mode": "ArtList",
                "format": "json",
                "maxrecords": "30",
                "sort": "hybridrel",
                "timespan": f"{self.timespan_hours}h",
            }
            response = requests.get(self.endpoint, params=params, headers={"User-Agent": USER_AGENT}, timeout=self.timeout)
            response.raise_for_status()
            data = response.json()
            for article in data.get("articles", [])[:25]:
                title = clean_text(article.get("title", ""))
                url = article.get("url", "")
                if not title or not url:
                    continue
                items.append(
                    NewsItem(
                        title=title,
                        url=url,
                        source=article.get("domain") or source_from_url(url),
                        category=category,
                        published_at=parse_datetime(article.get("seendate")),
                        summary=clean_text(article.get("snippet", "")),
                        image_url=article.get("socialimage", "") or article.get("image", ""),
                        adapters=[self.name],
                    )
                )
        return items

    @staticmethod
    def _query_for_category(category: str) -> str:
        queries = {
            "politics": '(India OR Indian) (politics OR election OR parliament OR government OR minister)',
            "films": '(India OR Indian OR Bollywood) (film OR movie OR cinema OR actor OR box office)',
            "sports": '(India OR Indian) (cricket OR sports OR match OR series OR football OR hockey)',
            "current_affairs": '(India OR Indian) (breaking news OR court OR economy OR weather OR policy OR current affairs)',
            "international": '(India OR Indian) (world OR global OR US OR China OR Russia OR Pakistan OR United Nations)',
        }
        return queries.get(category, "India news")


def guess_category(text: str) -> str:
    lowered = clean_text(text).lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            return category
    return "current_affairs"


def collect_news(config: Config) -> tuple[list[NewsItem], list[dict]]:
    adapters: list[SourceAdapter] = []
    if config.enable_rss:
        adapters.append(RSSAdapter(config.rss_feeds))
    if config.enable_google_trends and config.google_trends_rss_url:
        adapters.append(GoogleTrendsAdapter(config.google_trends_rss_url))
    if config.enable_gdelt:
        adapters.append(GDELTAdapter(config.rss_feeds.keys() or []))

    items: list[NewsItem] = []
    logs: list[dict] = []
    for adapter in adapters:
        try:
            fetched = adapter.fetch()
            items.extend(fetched)
            logs.append({"adapter": adapter.name, "status": "ok", "count": len(fetched)})
        except Exception as exc:
            logs.append({"adapter": adapter.name, "status": "error", "error": str(exc)})
    return items, logs


def enrich_article_images(items: list[NewsItem], limit: int = 80, timeout: int = 12) -> dict:
    inspected = 0
    filled = 0
    summary_filled = 0
    errors = 0
    for item in items[:limit]:
        needs_image = not item.image_url
        needs_summary = needs_better_summary(item.summary, item.title)
        if not needs_image and not needs_summary:
            continue
        inspected += 1
        try:
            metadata = extract_article_metadata(item.url, timeout=timeout)
        except Exception:
            errors += 1
            continue
        if needs_image and metadata["image_url"]:
            item.image_url = metadata["image_url"]
            filled += 1
        if needs_summary and metadata["description"]:
            item.summary = metadata["description"]
            summary_filled += 1
    return {
        "adapter": "article_image_enrichment",
        "status": "ok",
        "inspected": inspected,
        "filled": filled,
        "summary_filled": summary_filled,
        "errors": errors,
    }


def enrich_article_details(items: list[NewsItem], limit: int = 5, timeout: int = 12) -> dict:
    inspected = 0
    enriched = 0
    errors = 0
    for item in items[:limit]:
        if is_wrapper_url(item.url):
            continue
        inspected += 1
        original = item.summary
        try:
            metadata = extract_article_metadata(item.url, timeout=timeout)
        except Exception:
            errors += 1
            continue
        item.summary = richer_article_summary(item.summary, metadata.get("description", ""), metadata.get("article_text", ""))
        if item.summary != original:
            enriched += 1
    return {
        "adapter": "article_detail_enrichment",
        "status": "ok",
        "inspected": inspected,
        "enriched": enriched,
        "errors": errors,
    }


def extract_article_image(url: str, timeout: int = 12) -> str:
    return extract_article_metadata(url, timeout=timeout)["image_url"]


def extract_article_metadata(url: str, timeout: int = 12) -> dict[str, str]:
    if not url:
        return empty_article_metadata()
    if is_wrapper_url(url):
        return empty_article_metadata()
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
    response.raise_for_status()
    content_type = response.headers.get("content-type", "")
    if "html" not in content_type and "xml" not in content_type and content_type:
        return empty_article_metadata()

    soup = BeautifulSoup(response.text, "html.parser")
    description = extract_article_description(soup)
    article_text = extract_article_body_text(soup)
    image_url = ""
    for attr, value in IMAGE_META_KEYS:
        tag = soup.find("meta", attrs={attr: value})
        image_url = absolutize_image_url(tag.get("content") if tag else "", url)
        if image_url:
            return {"image_url": image_url, "description": description, "article_text": article_text}

    json_ld_image = extract_json_ld_image(soup, url)
    if json_ld_image:
        return {"image_url": json_ld_image, "description": description, "article_text": article_text}

    for img in soup.find_all("img")[:40]:
        image_url = image_from_img_tag(img, url)
        if image_url:
            return {"image_url": image_url, "description": description, "article_text": article_text}
    return {"image_url": "", "description": description, "article_text": article_text}


def empty_article_metadata() -> dict[str, str]:
    return {"image_url": "", "description": "", "article_text": ""}


def needs_better_summary(summary: str, title: str) -> bool:
    clean_summary = clean_text(summary)
    clean_title = clean_text(title)
    if len(clean_summary) < 80:
        return True
    return clean_summary.lower() == clean_title.lower()


def extract_article_description(soup: BeautifulSoup) -> str:
    for attr, value in DESCRIPTION_META_KEYS:
        tag = soup.find("meta", attrs={attr: value})
        description = clean_text(tag.get("content") if tag else "")
        if len(description) >= 40:
            return description
    return ""


def extract_article_body_text(soup: BeautifulSoup, max_chars: int = 1600) -> str:
    for tag in soup(["script", "style", "noscript", "svg", "form", "header", "footer", "nav", "aside"]):
        tag.decompose()
    roots = soup.find_all("article")
    if not roots:
        roots = soup.find_all("main")
    if not roots and soup.body:
        roots = [soup.body]

    paragraphs: list[str] = []
    seen: set[str] = set()
    for root in roots[:3]:
        for node in root.find_all(["p", "li"]):
            paragraph = clean_text(node.get_text(" "))
            if not useful_article_paragraph(paragraph):
                continue
            key = paragraph.lower()
            if key in seen:
                continue
            seen.add(key)
            paragraphs.append(paragraph)
            if len(" ".join(paragraphs)) >= max_chars:
                return truncate_words(" ".join(paragraphs), max_words=230, max_chars=max_chars)
    return truncate_words(" ".join(paragraphs), max_words=230, max_chars=max_chars)


def useful_article_paragraph(text: str) -> bool:
    paragraph = clean_text(text)
    if len(paragraph) < 55:
        return False
    lowered = paragraph.lower()
    blocked = (
        "advertisement",
        "also read",
        "read more",
        "subscribe",
        "follow us",
        "sign up",
        "download the app",
        "copyright",
        "all rights reserved",
        "click here",
    )
    if any(token in lowered for token in blocked):
        return False
    if len(paragraph.split()) < 9:
        return False
    return True


def richer_article_summary(existing: str, description: str, article_text: str) -> str:
    parts: list[str] = []
    for value in (existing, description, article_text):
        text = clean_text(value)
        if not text:
            continue
        if any(text.lower() == part.lower() for part in parts):
            continue
        parts.append(text)
    merged = " ".join(parts)
    return truncate_words(merged, max_words=240, max_chars=1650)


def publisher_source(feed_source: str, link: str, feed_url: str) -> str:
    if "google news" in feed_source.lower():
        return source_from_url(link)
    host_source = source_from_url(link)
    if "feedburner.com" in host_source:
        return source_from_url(feed_url)
    if feed_source and "records found" not in feed_source.lower():
        return feed_source
    return host_source


def is_wrapper_url(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return host.endswith("news.google.com") or host.endswith("trends.google.com")


def extract_json_ld_image(soup: BeautifulSoup, base_url: str) -> str:
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        for candidate in iter_json_images(data):
            image_url = absolutize_image_url(candidate, base_url)
            if image_url:
                return image_url
    return ""


def iter_json_images(value):
    if isinstance(value, dict):
        image = value.get("image") or value.get("thumbnailUrl") or value.get("primaryImageOfPage")
        if isinstance(image, str):
            yield image
        elif isinstance(image, list):
            for item in image:
                yield from iter_json_images(item)
        elif isinstance(image, dict):
            url = image.get("url") or image.get("contentUrl")
            if url:
                yield url
        for child in value.values():
            if isinstance(child, (dict, list)):
                yield from iter_json_images(child)
    elif isinstance(value, list):
        for item in value:
            yield from iter_json_images(item)


def image_from_img_tag(img, base_url: str) -> str:
    width = parse_int(img.get("width") or img.get("data-width"))
    height = parse_int(img.get("height") or img.get("data-height"))
    if width and height and (width < 300 or height < 180):
        return ""
    attrs = " ".join(str(img.get(name, "")) for name in ("alt", "class", "id", "src")).lower()
    if any(token in attrs for token in ("logo", "icon", "sprite", "avatar", "author", "placeholder", "tracking")):
        return ""
    for attr in IMAGE_ATTRS:
        image_url = absolutize_image_url(img.get(attr), base_url)
        if image_url:
            return image_url
    srcset = img.get("srcset") or img.get("data-srcset")
    if srcset:
        candidates = [part.strip().split(" ")[0] for part in srcset.split(",") if part.strip()]
        for candidate in reversed(candidates):
            image_url = absolutize_image_url(candidate, base_url)
            if image_url:
                return image_url
    return ""


def absolutize_image_url(value: object, base_url: str) -> str:
    url = clean_text(value)
    if not url or url.startswith("data:"):
        return ""
    absolute = urljoin(base_url, url)
    parsed = urlparse(absolute)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    lowered = absolute.lower()
    if any(token in lowered for token in ("logo", "sprite", "favicon", "icon-")):
        return ""
    return absolute


def parse_int(value: object) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def mock_news_items(now=None) -> list[NewsItem]:
    base = now or utcnow()
    samples = [
        (
            "politics",
            "India parliament debates new digital governance bill after all-party meeting",
            "https://example.com/politics/digital-governance-bill",
            "Example Politics",
        ),
        (
            "films",
            "Bollywood star announces pan-India film after record opening weekend",
            "https://example.com/films/pan-india-record-opening",
            "Example Films",
        ),
        (
            "sports",
            "India cricket team seals series win as young batter scores century",
            "https://example.com/sports/india-cricket-series-win",
            "Example Sports",
        ),
        (
            "current_affairs",
            "Supreme Court hears major public policy case with nationwide impact",
            "https://example.com/current-affairs/supreme-court-policy-case",
            "Example Current Affairs",
        ),
        (
            "international",
            "World leaders respond as India calls for renewed diplomatic dialogue",
            "https://example.com/world/india-diplomatic-dialogue",
            "Example International",
        ),
        (
            "sports",
            "Indian badminton pair reaches final after dramatic comeback",
            "https://example.com/sports/badminton-final-comeback",
            "Example Sports",
        ),
    ]
    return [
        NewsItem(
            category=category,
            title=title,
            url=url,
            source=source,
            published_at=base - timedelta(minutes=15 * index),
            summary=f"Mock summary for {title}",
            image_url="",
            adapters=["mock"],
        )
        for index, (category, title, url, source) in enumerate(samples)
    ]
