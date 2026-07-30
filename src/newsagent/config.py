from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

from .models import CATEGORIES


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    value = os.getenv(name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def _handle(value: str, fallback: str) -> str:
    text = (value or fallback).strip()
    if not text:
        text = fallback
    if not text.startswith("@"):
        text = f"@{text}"
    return text


def default_rss_feeds() -> dict[str, list[str]]:
    return {
        "politics": [
            "https://feeds.feedburner.com/ndtvnews-india-news",
            "https://indianexpress.com/section/india/feed/",
            "https://www.indiatoday.in/rss/1206514",
        ],
        "films": [
            "https://feeds.feedburner.com/ndtvmovies-latest",
            "https://indianexpress.com/section/entertainment/feed/",
            "https://www.indiatoday.in/rss/1206551",
        ],
        "sports": [
            "https://feeds.feedburner.com/ndtvsports-latest",
            "https://indianexpress.com/section/sports/feed/",
            "https://www.indiatoday.in/rss/1206550",
        ],
        "current_affairs": [
            "https://feeds.feedburner.com/ndtvnews-top-stories",
            "https://indianexpress.com/section/explained/feed/",
            "https://www.indiatoday.in/rss/home",
        ],
        "international": [
            "https://feeds.feedburner.com/ndtvnews-world-news",
            "https://indianexpress.com/section/world/feed/",
            "https://www.indiatoday.in/rss/1206577",
        ],
    }


def parse_rss_feeds(raw: str | None) -> dict[str, list[str]]:
    if not raw:
        return default_rss_feeds()
    feeds: dict[str, list[str]] = {category: [] for category in CATEGORIES}
    for part in raw.replace("\n", ";").split(";"):
        if not part.strip():
            continue
        if "=" in part:
            category, url = part.split("=", 1)
        elif "|" in part:
            category, url = part.split("|", 1)
        else:
            category, url = "current_affairs", part
        category = category.strip()
        if category not in feeds:
            category = "current_affairs"
        feeds[category].append(url.strip())
    return {category: urls for category, urls in feeds.items() if urls}


@dataclass
class Config:
    project_root: Path = field(default_factory=lambda: Path.cwd())
    brand_name: str = field(default_factory=lambda: os.getenv("BRAND_NAME", "Samachar Bharat"))
    brand_handle: str = field(default_factory=lambda: _handle(os.getenv("BRAND_HANDLE", "@smachar.bh"), "@smachar.bh"))
    brand_tagline: str = field(
        default_factory=lambda: os.getenv("BRAND_TAGLINE", "Bharat in 5 slides. Every 3 hours.")
    )
    brand_bio: str = field(
        default_factory=lambda: os.getenv(
            "BRAND_BIO",
            "Top Bharat stories in 5 quick slides. Politics, films, sports, current affairs and world news.",
        )
    )
    data_dir: Path = field(default_factory=lambda: Path(os.getenv("NEWSAGENT_DATA_DIR", "data")))
    assets_dir: Path = field(default_factory=lambda: Path(os.getenv("NEWSAGENT_ASSETS_DIR", "assets")))
    db_path: Path = field(default_factory=lambda: Path(os.getenv("NEWSAGENT_SESSION_PATH", "data/session-store.json")))
    timezone: str = field(default_factory=lambda: os.getenv("TIMEZONE", "Asia/Kolkata"))
    cycle_hours: int = field(default_factory=lambda: _int("CYCLE_HOURS", 3))
    dedupe_hours: int = field(default_factory=lambda: _int("DEDUPE_HOURS", 48))
    draft_min_items: int = field(default_factory=lambda: _int("DRAFT_MIN_ITEMS", 4))
    draft_max_items: int = field(default_factory=lambda: _int("DRAFT_MAX_ITEMS", 5))
    image_policy: str = field(default_factory=lambda: os.getenv("IMAGE_POLICY", "branded_cards"))
    require_real_images: bool = field(default_factory=lambda: _bool("REQUIRE_REAL_IMAGES", False))
    image_enrichment_limit: int = field(default_factory=lambda: _int("IMAGE_ENRICHMENT_LIMIT", 80))
    dashboard_host: str = field(default_factory=lambda: os.getenv("DASHBOARD_HOST", "127.0.0.1"))
    dashboard_port: int = field(default_factory=lambda: _int("DASHBOARD_PORT", 8000))
    dashboard_token: str = field(default_factory=lambda: os.getenv("DASHBOARD_TOKEN", ""))
    enable_rss: bool = field(default_factory=lambda: _bool("ENABLE_RSS", True))
    enable_gdelt: bool = field(default_factory=lambda: _bool("ENABLE_GDELT", True))
    enable_google_trends: bool = field(default_factory=lambda: _bool("ENABLE_GOOGLE_TRENDS", True))
    rss_feeds: dict[str, list[str]] = field(default_factory=lambda: parse_rss_feeds(os.getenv("RSS_FEEDS")))
    google_trends_rss_url: str = field(
        default_factory=lambda: os.getenv("GOOGLE_TRENDS_RSS_URL", "https://trends.google.com/trending/rss?geo=IN")
    )
    reference_instagram_pages: list[str] = field(default_factory=lambda: _split_csv(os.getenv("REFERENCE_INSTAGRAM_PAGES")))
    meta_graph_version: str = field(default_factory=lambda: os.getenv("META_GRAPH_VERSION", "v26.0"))
    meta_api_host: str = field(default_factory=lambda: os.getenv("META_API_HOST", ""))
    instagram_business_account_id: str = field(default_factory=lambda: os.getenv("INSTAGRAM_BUSINESS_ACCOUNT_ID", ""))
    meta_access_token: str = field(default_factory=lambda: os.getenv("META_ACCESS_TOKEN", ""))
    public_asset_base_url: str = field(default_factory=lambda: os.getenv("PUBLIC_ASSET_BASE_URL", ""))
    public_asset_token: str = field(default_factory=lambda: os.getenv("PUBLIC_ASSET_TOKEN", ""))

    def __post_init__(self) -> None:
        self.brand_name = self.brand_name.strip() or "Samachar Bharat"
        self.brand_handle = _handle(self.brand_handle, "@smachar.bh")
        self.brand_tagline = self.brand_tagline.strip()
        self.brand_bio = self.brand_bio.strip()
        self.meta_graph_version = self.meta_graph_version.strip().strip("/") or "v26.0"
        self.meta_api_host = self._normalize_meta_api_host(self.meta_api_host)
        self.instagram_business_account_id = self.instagram_business_account_id.strip()
        self.meta_access_token = self.meta_access_token.strip()
        self.public_asset_base_url = self.public_asset_base_url.strip()
        self.public_asset_token = self.public_asset_token.strip()
        self.image_policy = self.image_policy.strip().lower() or "branded_cards"
        if self.image_policy not in {"branded_cards", "article_images"}:
            self.image_policy = "branded_cards"
        self.data_dir = self._resolve(self.data_dir)
        self.assets_dir = self._resolve(self.assets_dir)
        self.db_path = self._resolve(self.db_path)

    @staticmethod
    def _normalize_meta_api_host(host: str) -> str:
        text = host.strip()
        if text.lower() in {"", "auto"}:
            return ""
        text = text.removeprefix("https://").removeprefix("http://").strip("/")
        return text

    @property
    def resolved_meta_api_host(self) -> str:
        if self.meta_api_host:
            return self.meta_api_host
        if self.meta_access_token.upper().startswith("IG"):
            return "graph.instagram.com"
        return "graph.facebook.com"

    @property
    def meta_api_base_url(self) -> str:
        return f"https://{self.resolved_meta_api_host}/{self.meta_graph_version}"

    @property
    def meta_auth_flow_label(self) -> str:
        if self.resolved_meta_api_host == "graph.instagram.com":
            return "Instagram Login / Instagram API"
        return "Facebook Login / Meta Graph API"

    def _resolve(self, path: Path) -> Path:
        if path.is_absolute():
            return path
        return (self.project_root / path).resolve()

    @property
    def can_publish_to_meta(self) -> bool:
        return bool(
            self.instagram_business_account_id
            and self.meta_access_token
            and self.public_asset_base_url.startswith("https://")
        )

    @property
    def uses_article_images(self) -> bool:
        return self.image_policy == "article_images"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.assets_dir.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)


def load_config(project_root: Path | None = None, env_file: Path | None = None) -> Config:
    root = project_root or Path.cwd()
    dotenv_path = env_file or root / ".env"
    if dotenv_path.exists():
        load_dotenv(dotenv_path)
    config = Config(project_root=root)
    config.ensure_dirs()
    return config
