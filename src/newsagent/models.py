from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from .utils import canonicalize_url, clean_text, source_from_url, story_key


CATEGORIES = ("politics", "films", "sports", "current_affairs", "international")


@dataclass
class NewsItem:
    title: str
    url: str
    source: str
    category: str
    published_at: datetime | None = None
    summary: str = ""
    image_url: str = ""
    source_count: int = 1
    adapters: list[str] = field(default_factory=list)
    score: float = 0.0

    def __post_init__(self) -> None:
        self.title = clean_text(self.title)
        self.summary = clean_text(self.summary)
        self.url = canonicalize_url(self.url)
        self.source = clean_text(self.source) or source_from_url(self.url)
        if self.category not in CATEGORIES:
            self.category = "current_affairs"
        if self.published_at and self.published_at.tzinfo is None:
            self.published_at = self.published_at.replace(tzinfo=timezone.utc)

    @property
    def key(self) -> str:
        return story_key(self.title, self.url)


@dataclass
class DraftStory:
    key: str
    title: str
    url: str
    source: str
    category: str
    published_at: datetime | None
    summary: str
    image_url: str
    source_count: int
    score: float
    slide_path: str = ""
    rights_risk: str = "not_assessed"


@dataclass
class Draft:
    id: str
    created_at: datetime
    status: str
    stories: list[DraftStory]
    caption: str
    manual_export_path: str = ""
    published_at: datetime | None = None
    publish_response: str = ""
    log: dict = field(default_factory=dict)
