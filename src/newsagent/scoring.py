from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from .models import CATEGORIES, NewsItem
from .utils import cluster_key, utcnow


INDIA_TERMS = {
    "india",
    "indian",
    "bharat",
    "delhi",
    "mumbai",
    "bengaluru",
    "chennai",
    "kolkata",
    "hyderabad",
    "modi",
    "lok sabha",
    "rajya sabha",
}


def cluster_items(items: list[NewsItem]) -> list[NewsItem]:
    clusters: dict[str, list[NewsItem]] = defaultdict(list)
    for item in items:
        key = cluster_key(item.title) or item.key
        clusters[key].append(item)

    merged: list[NewsItem] = []
    for cluster in clusters.values():
        cluster.sort(key=lambda item: item.published_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        primary = cluster[0]
        primary.source_count = max(1, len({item.source for item in cluster}))
        adapters = sorted({adapter for item in cluster for adapter in item.adapters})
        primary.adapters = adapters or primary.adapters
        if not primary.image_url:
            primary.image_url = next((item.image_url for item in cluster if item.image_url), "")
        merged.append(primary)
    return merged


def score_items(items: list[NewsItem], now=None) -> list[NewsItem]:
    current = now or utcnow()
    for item in items:
        published = item.published_at or current
        age_hours = max(0.0, (current - published).total_seconds() / 3600)
        recency = max(0.0, 1.0 - min(age_hours, 24) / 24)
        india = india_relevance(item)
        item.score = (
            recency * 45
            + min(item.source_count, 4) * 12
            + india * 25
            + (8 if item.image_url else 0)
            + (5 if item.category in CATEGORIES else 0)
        )
    return sorted(items, key=lambda item: item.score, reverse=True)


def india_relevance(item: NewsItem) -> float:
    text = f"{item.title} {item.summary} {item.source}".lower()
    hits = sum(1 for term in INDIA_TERMS if term in text)
    if hits >= 2:
        return 1.0
    if hits == 1:
        return 0.75
    return 0.25 if item.category in {"international", "current_affairs"} else 0.0


def select_balanced(items: list[NewsItem], min_items: int = 4, max_items: int = 5) -> list[NewsItem]:
    by_category: dict[str, list[NewsItem]] = defaultdict(list)
    for item in sorted(items, key=lambda story: story.score, reverse=True):
        by_category[item.category].append(item)

    selected: list[NewsItem] = []
    selected_keys: set[str] = set()
    for category in CATEGORIES:
        if len(selected) >= max_items:
            break
        if by_category.get(category):
            item = by_category[category][0]
            selected.append(item)
            selected_keys.add(item.key)

    if len(selected) < min_items:
        for item in sorted(items, key=lambda story: story.score, reverse=True):
            if item.key in selected_keys:
                continue
            selected.append(item)
            selected_keys.add(item.key)
            if len(selected) >= min_items:
                break

    return selected[:max_items]
