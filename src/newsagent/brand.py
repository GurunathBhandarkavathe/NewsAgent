from __future__ import annotations

from dataclasses import dataclass

from .config import Config


@dataclass(frozen=True)
class ProductionCheck:
    name: str
    status: str
    detail: str

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    @property
    def blocks_publish(self) -> bool:
        return self.status == "block"


def profile_fields(config: Config) -> dict[str, str]:
    return {
        "name": config.brand_name,
        "handle": config.brand_handle,
        "tagline": config.brand_tagline,
        "bio": config.brand_bio,
        "category": "News & media website",
        "caption_signature": f"Follow {config.brand_handle} for {config.brand_tagline}",
    }


def production_checks(config: Config) -> list[ProductionCheck]:
    source_count = sum(
        (
            bool(config.enable_rss),
            bool(config.enable_gdelt),
            bool(config.enable_google_trends),
        )
    )
    checks = [
        ProductionCheck("Brand", "ok" if config.brand_name else "block", config.brand_name or "BRAND_NAME is empty"),
        ProductionCheck("Handle", "ok" if config.brand_handle else "block", config.brand_handle or "BRAND_HANDLE is empty"),
        ProductionCheck(
            "Dashboard token",
            "ok" if config.dashboard_token else "warn",
            "set" if config.dashboard_token else "set DASHBOARD_TOKEN before exposing the dashboard",
        ),
        ProductionCheck(
            "Dashboard bind",
            "ok" if config.dashboard_host in {"127.0.0.1", "localhost"} else "warn",
            config.dashboard_host,
        ),
        ProductionCheck(
            "Image policy",
            "ok" if not config.uses_article_images else "warn",
            "branded cards only; no news-channel images"
            if not config.uses_article_images
            else "article images can appear in drafts",
        ),
        ProductionCheck(
            "Sources",
            "ok" if source_count else "block",
            f"{source_count} enabled adapters",
        ),
        ProductionCheck(
            "Meta account",
            "ok" if config.instagram_business_account_id else "warn",
            "configured" if config.instagram_business_account_id else "manual export until INSTAGRAM_BUSINESS_ACCOUNT_ID is set",
        ),
        ProductionCheck(
            "Meta token",
            "ok" if config.meta_access_token else "warn",
            "configured" if config.meta_access_token else "manual export until META_ACCESS_TOKEN is set",
        ),
        ProductionCheck(
            "Public asset URL",
            "ok" if config.public_asset_base_url.startswith("https://") else "warn",
            config.public_asset_base_url or "manual export until PUBLIC_ASSET_BASE_URL is an HTTPS URL",
        ),
        ProductionCheck("Approval gate", "ok", "required before publish"),
    ]
    return checks


def publish_ready(config: Config) -> bool:
    return config.can_publish_to_meta
