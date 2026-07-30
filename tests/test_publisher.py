from __future__ import annotations

from pathlib import Path

from newsagent.caption import PUBLISH_CAPTION_MAX_CHARS
from newsagent.db import Database
from newsagent.pipeline import run_cycle
from newsagent.publisher import Publisher

from helpers import make_config


class FakeResponse:
    def __init__(self, payload: dict):
        self.payload = payload
        self.text = str(payload)

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self.payload


def test_meta_publisher_creates_separate_image_posts_and_publish(monkeypatch, tmp_path: Path) -> None:
    config = make_config(
        tmp_path,
        instagram_business_account_id="17890000000000000",
        meta_access_token="test-token",
        public_asset_base_url="https://cdn.example.test/newsagent/",
    )
    db = Database(config.db_path)
    draft = run_cycle(config, db, use_mock=True)
    assert draft is not None

    calls: list[tuple[str, dict]] = []

    def fake_post(url: str, data: dict, timeout: int):
        calls.append((url, data))
        if url.endswith("/media_publish"):
            return FakeResponse({"id": f"published-media-id-{len(calls)}"})
        return FakeResponse({"id": f"container-{len(calls)}"})

    monkeypatch.setattr("newsagent.publisher.requests.post", fake_post)

    result = Publisher(config).publish(draft)

    container_calls = calls[::2]
    publish_calls = calls[1::2]

    assert result.status == "published"
    assert result.response["post_format"] == "separate_posts"
    assert len(result.response["posts"]) == len(draft.stories)
    assert len(container_calls) == len(draft.stories)
    assert len(publish_calls) == len(draft.stories)
    assert all(call[1]["image_url"].startswith("https://cdn.example.test/newsagent/drafts/") for call in container_calls)
    assert all("is_carousel_item" not in call[1] for call in container_calls)
    assert all("media_type" not in call[1] for call in container_calls)
    assert all(len(call[1]["caption"]) <= PUBLISH_CAPTION_MAX_CHARS for call in container_calls)
    assert [call[1]["creation_id"] for call in publish_calls] == [
        f"container-{index}" for index in range(1, len(calls), 2)
    ]
    assert all(call[1]["access_token"] == "test-token" for call in calls)
    assert all(call[0].startswith("https://graph.facebook.com/v26.0/") for call in calls)


def test_meta_publisher_uses_instagram_host_for_igaa_tokens(monkeypatch, tmp_path: Path) -> None:
    config = make_config(
        tmp_path,
        instagram_business_account_id="17890000000000000",
        meta_access_token="IGAA-token-value",
        public_asset_base_url="https://cdn.example.test/newsagent/",
    )
    db = Database(config.db_path)
    draft = run_cycle(config, db, use_mock=True)
    assert draft is not None

    calls: list[str] = []

    def fake_post(url: str, data: dict, timeout: int):
        calls.append(url)
        if url.endswith("/media_publish"):
            return FakeResponse({"id": "published-media-id"})
        if data.get("media_type") == "CAROUSEL":
            return FakeResponse({"id": "carousel-container-id"})
        return FakeResponse({"id": f"child-{len(calls)}"})

    monkeypatch.setattr("newsagent.publisher.requests.post", fake_post)

    result = Publisher(config).publish(draft)

    assert result.status == "published"
    assert calls
    assert all(call.startswith("https://graph.instagram.com/v26.0/") for call in calls)


def test_meta_publisher_trims_existing_overlong_caption(monkeypatch, tmp_path: Path) -> None:
    config = make_config(
        tmp_path,
        post_format="carousel",
        instagram_business_account_id="17890000000000000",
        meta_access_token="test-token",
        public_asset_base_url="https://cdn.example.test/newsagent/",
    )
    db = Database(config.db_path)
    draft = run_cycle(config, db, use_mock=True)
    assert draft is not None
    draft.caption = "Samachar Bharat trend watch:\n" + ("Long caption detail. " * 250)

    calls: list[tuple[str, dict]] = []

    def fake_post(url: str, data: dict, timeout: int):
        calls.append((url, data))
        if url.endswith("/media_publish"):
            return FakeResponse({"id": "published-media-id"})
        if data.get("media_type") == "CAROUSEL":
            return FakeResponse({"id": "carousel-container-id"})
        return FakeResponse({"id": f"child-{len(calls)}"})

    monkeypatch.setattr("newsagent.publisher.requests.post", fake_post)

    result = Publisher(config).publish(draft)

    container_caption = calls[-2][1]["caption"]
    assert result.status == "published"
    assert len(container_caption) <= PUBLISH_CAPTION_MAX_CHARS
