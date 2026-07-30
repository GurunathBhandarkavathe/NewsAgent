from __future__ import annotations

from pathlib import Path

from newsagent.brand import production_checks, profile_fields
from newsagent.config import Config
from newsagent.db import Database
from newsagent.pipeline import run_cycle

from helpers import make_config


def test_default_brand_config_is_samachar_bharat(tmp_path: Path) -> None:
    config = make_config(tmp_path, brand_handle="smachar.bh")
    profile = profile_fields(config)

    assert config.brand_name == "Samachar Bharat"
    assert config.brand_handle == "@smachar.bh"
    assert profile["name"] == "Samachar Bharat"
    assert profile["handle"] == "@smachar.bh"
    assert "Bharat in 5 slides" in profile["tagline"]


def test_caption_uses_samachar_bharat_brand(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    db = Database(config.db_path)
    draft = run_cycle(config, db, use_mock=True)
    assert draft is not None

    assert draft.caption.startswith("Samachar Bharat trend watch:")
    assert "Follow @smachar.bh" in draft.caption
    assert "#SamacharBharat" in draft.caption


def test_custom_brand_values_flow_into_caption(tmp_path: Path) -> None:
    config = make_config(
        tmp_path,
        brand_name="DeshByte",
        brand_handle="deshbyte",
        brand_tagline="India's sharpest 5-slide briefing.",
    )
    db = Database(config.db_path)
    draft = run_cycle(config, db, use_mock=True)
    assert draft is not None

    assert draft.caption.startswith("DeshByte trend watch:")
    assert "Follow @deshbyte for India's sharpest 5-slide briefing." in draft.caption


def test_production_checks_warn_until_meta_publish_is_ready(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    checks = {check.name: check for check in production_checks(config)}

    assert checks["Dashboard token"].status == "warn"
    assert checks["Image policy"].status == "ok"
    assert "no news-channel images" in checks["Image policy"].detail
    assert checks["Meta account"].status == "warn"
    assert checks["Public asset URL"].status == "warn"
    assert checks["Approval gate"].status == "ok"
    assert config.can_publish_to_meta is False


def test_meta_publish_requires_https_public_asset_url(tmp_path: Path) -> None:
    http_config = make_config(
        tmp_path / "http",
        instagram_business_account_id="17890000000000000",
        meta_access_token="test-token",
        public_asset_base_url="http://cdn.example.test/newsagent/",
    )
    https_config = Config(
        project_root=tmp_path / "https",
        data_dir=tmp_path / "https" / "data",
        assets_dir=tmp_path / "https" / "assets",
        db_path=tmp_path / "https" / "data" / "session-store.json",
        instagram_business_account_id="17890000000000000",
        meta_access_token="test-token",
        public_asset_base_url="https://cdn.example.test/newsagent/",
    )

    assert http_config.can_publish_to_meta is False
    assert https_config.can_publish_to_meta is True
