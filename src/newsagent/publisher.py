from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urljoin

import requests

from .config import Config
from .meta_api import meta_response_error_detail, redact_sensitive_meta_text
from .models import Draft
from .utils import ensure_relative_to, utcnow


@dataclass
class PublishResult:
    status: str
    message: str
    response: dict
    manual_export_path: str = ""


class Publisher:
    def __init__(self, config: Config):
        self.config = config

    def publish(self, draft: Draft) -> PublishResult:
        if not self.config.can_publish_to_meta:
            export_path = export_manual_package(draft, self.config)
            return PublishResult(
                status="exported",
                message="Meta credentials or HTTPS PUBLIC_ASSET_BASE_URL missing; exported manual posting package.",
                response={"mode": "manual_export"},
                manual_export_path=str(export_path),
            )
        return self._publish_to_meta(draft)

    def _publish_to_meta(self, draft: Draft) -> PublishResult:
        base = self.config.meta_api_base_url
        children: list[str] = []
        for story in draft.stories:
            image_url = self._public_url_for_slide(story.slide_path)
            data = self._post(
                f"{base}/{self.config.instagram_business_account_id}/media",
                {
                    "image_url": image_url,
                    "is_carousel_item": "true",
                    "access_token": self.config.meta_access_token,
                },
            )
            children.append(data["id"])

        container = self._post(
            f"{base}/{self.config.instagram_business_account_id}/media",
            {
                "media_type": "CAROUSEL",
                "children": ",".join(children),
                "caption": draft.caption,
                "access_token": self.config.meta_access_token,
            },
        )
        creation_id = container["id"]

        publish_response = None
        for attempt in range(4):
            try:
                publish_response = self._post(
                    f"{base}/{self.config.instagram_business_account_id}/media_publish",
                    {"creation_id": creation_id, "access_token": self.config.meta_access_token},
                )
                break
            except requests.HTTPError:
                if attempt == 3:
                    raise
                time.sleep(3)

        return PublishResult(
            status="published",
            message=f"Published to Instagram through {self.config.meta_auth_flow_label}.",
            response={"container_id": creation_id, "children": children, "publish": publish_response},
        )

    def _public_url_for_slide(self, slide_path: str) -> str:
        relative = ensure_relative_to(Path(slide_path), self.config.assets_dir)
        quoted = "/".join(quote(part) for part in relative.split("/"))
        return urljoin(self.config.public_asset_base_url.rstrip("/") + "/", quoted)

    def _post(self, url: str, data: dict) -> dict:
        response = requests.post(url, data=data, timeout=60)
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            detail = meta_response_error_detail(response, self.config)
            message = redact_sensitive_meta_text(str(exc), self.config)
            raise requests.HTTPError(f"{message}: {detail}") from exc
        return response.json()


def export_manual_package(draft: Draft, config: Config) -> Path:
    draft_dir = config.assets_dir / "drafts" / draft.id
    export_dir = draft_dir / "manual-post"
    export_dir.mkdir(parents=True, exist_ok=True)

    for story in draft.stories:
        if story.slide_path:
            source = Path(story.slide_path)
            if source.exists():
                shutil.copy2(source, export_dir / source.name)

    (export_dir / "caption.txt").write_text(draft.caption, encoding="utf-8")
    sources = [
        {
            "title": story.title,
            "url": story.url,
            "source": story.source,
            "category": story.category,
            "rights_risk": story.rights_risk,
        }
        for story in draft.stories
    ]
    (export_dir / "sources.json").write_text(json.dumps(sources, indent=2), encoding="utf-8")
    (export_dir / "README.txt").write_text(
        f"Manual Instagram package generated for {config.brand_name} after approval.\n"
        "Upload the slides in filename order as one carousel and paste caption.txt.\n"
        "Review image reuse rights before publishing.\n",
        encoding="utf-8",
    )
    return export_dir
