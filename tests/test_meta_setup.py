from __future__ import annotations

from pathlib import Path

import requests

from newsagent.dashboard import create_app
from newsagent.db import Database
from newsagent.env_store import save_env_values
from newsagent.meta import check_meta_connection
from newsagent.pipeline import run_cycle

from helpers import make_config


class FakeResponse:
    text = "{}"

    def __init__(self, payload: dict):
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self.payload


class ErrorResponse:
    def __init__(self, payload: dict):
        self.payload = payload
        self.text = str(payload)

    def raise_for_status(self) -> None:
        raise requests.HTTPError("400 Client Error: Bad Request for url with access_token=SHOULD_NOT_LEAK")

    def json(self) -> dict:
        return self.payload


def test_env_store_saves_values_without_dropping_comments(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("# Brand\nBRAND_NAME=Samachar Bharat\nMETA_ACCESS_TOKEN=old\n", encoding="utf-8")

    save_env_values(
        env_path,
        {
            "META_ACCESS_TOKEN": "new token",
            "PUBLIC_ASSET_BASE_URL": "https://example.com/public-assets/token/",
        },
    )

    content = env_path.read_text(encoding="utf-8")
    assert "# Brand" in content
    assert 'META_ACCESS_TOKEN="new token"' in content
    assert "PUBLIC_ASSET_BASE_URL=https://example.com/public-assets/token/" in content


def test_dashboard_meta_setup_saves_env_and_public_asset_route(tmp_path: Path) -> None:
    config = make_config(tmp_path, public_asset_token="asset-token")
    db = Database(config.db_path)
    draft = run_cycle(config, db, use_mock=True)
    assert draft is not None

    app = create_app(config, db)
    client = app.test_client()

    response = client.post(
        "/setup/meta",
        data={
            "meta_graph_version": "v26.0",
            "meta_api_host": "graph.instagram.com",
            "instagram_business_account_id": "17890000000000000",
            "meta_access_token": "token-value",
            "public_asset_token": "asset-token",
            "public_asset_base_url": "https://example.com/public-assets/asset-token/",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert config.can_publish_to_meta is True
    content = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "META_API_HOST=graph.instagram.com" in content
    assert "INSTAGRAM_BUSINESS_ACCOUNT_ID=17890000000000000" in content
    assert "PUBLIC_ASSET_TOKEN=asset-token" in content

    relative = Path(draft.stories[0].slide_path).relative_to(config.assets_dir).as_posix()
    assert client.get(f"/public-assets/asset-token/{relative}").status_code == 200
    assert client.get(f"/public-assets/wrong/{relative}").status_code == 404


def test_meta_connection_check_uses_graph_without_posting(monkeypatch, tmp_path: Path) -> None:
    config = make_config(
        tmp_path,
        instagram_business_account_id="17890000000000000",
        meta_access_token="token-value",
        public_asset_base_url="https://example.com/public-assets/asset-token/",
    )
    calls: list[tuple[str, dict]] = []

    def fake_get(url: str, params: dict, timeout: int):
        calls.append((url, params))
        return FakeResponse({"id": "17890000000000000", "username": "smachar.bh", "media_count": 0})

    monkeypatch.setattr("newsagent.meta.requests.get", fake_get)

    result = check_meta_connection(config)

    assert result.ok is True
    assert result.account["username"] == "smachar.bh"
    assert calls
    assert calls[0][0].startswith("https://graph.facebook.com/v26.0/")
    assert calls[0][1]["fields"] == "id,username,media_count"


def test_meta_connection_uses_instagram_host_for_igaa_tokens(monkeypatch, tmp_path: Path) -> None:
    config = make_config(
        tmp_path,
        instagram_business_account_id="17890000000000000",
        meta_access_token="IGAA-token-value",
        public_asset_base_url="https://example.com/public-assets/asset-token/",
    )
    calls: list[str] = []

    def fake_get(url: str, params: dict, timeout: int):
        calls.append(url)
        return FakeResponse({"id": "17890000000000000", "username": "smachar.bh", "media_count": 0})

    monkeypatch.setattr("newsagent.meta.requests.get", fake_get)

    result = check_meta_connection(config)

    assert result.ok is True
    assert calls == ["https://graph.instagram.com/v26.0/17890000000000000"]


def test_meta_connection_redacts_tokens_from_errors(monkeypatch, tmp_path: Path) -> None:
    secret = "IGAA" + "a" * 44
    config = make_config(
        tmp_path,
        instagram_business_account_id="17890000000000000",
        meta_access_token=secret,
        public_asset_base_url="https://example.com/public-assets/asset-token/",
    )

    def fake_get(url: str, params: dict, timeout: int):
        return ErrorResponse(
            {
                "error": {
                    "message": f"Invalid token {secret}",
                    "type": "OAuthException",
                    "code": 190,
                    "fbtrace_id": "trace123",
                }
            }
        )

    monkeypatch.setattr("newsagent.meta.requests.get", fake_get)

    result = check_meta_connection(config)

    details = "\n".join(check["detail"] for check in result.checks)
    assert result.ok is False
    assert secret not in details
    assert "SHOULD_NOT_LEAK" not in details
    assert "[redacted]" in details
    assert "OAuthException code 190" in details
