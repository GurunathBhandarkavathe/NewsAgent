from __future__ import annotations

from pathlib import Path

from newsagent.dashboard import create_app
from newsagent.db import Database
from newsagent.pipeline import run_cycle

from helpers import make_config


def test_dashboard_renders_index_detail_and_asset(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    db = Database(config.db_path)
    draft = run_cycle(config, db, use_mock=True)
    assert draft is not None

    app = create_app(config, db)
    client = app.test_client()

    index = client.get("/")
    brand = client.get("/brand")
    detail = client.get(f"/draft/{draft.id}")
    asset = client.get("/assets/" + Path(draft.stories[0].slide_path).relative_to(config.assets_dir).as_posix())

    assert index.status_code == 200
    assert b"Samachar Bharat Drafts" in index.data
    assert draft.id.encode() in index.data
    assert b"slide-01.jpg" in index.data
    assert brand.status_code == 200
    assert b"@smachar.bh" in brand.data
    assert b"no news-channel images" in brand.data
    assert b"Production" in brand.data
    assert detail.status_code == 200
    assert b"Samachar Bharat Draft" in detail.data
    assert b"Approve" in detail.data
    assert b"Rights:" in detail.data
    assert asset.status_code == 200
    assert asset.content_type == "image/jpeg"


def test_dashboard_requires_token_when_configured(tmp_path: Path) -> None:
    config = make_config(tmp_path, dashboard_token="secret-token")
    db = Database(config.db_path)
    draft = run_cycle(config, db, use_mock=True)
    assert draft is not None

    app = create_app(config, db)
    client = app.test_client()

    assert client.get("/").status_code == 403
    assert client.get("/?token=secret-token").status_code == 200
    assert client.get(f"/draft/{draft.id}", headers={"X-NewsAgent-Token": "secret-token"}).status_code == 200


def test_dashboard_approval_exports_manual_package_without_meta_credentials(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    db = Database(config.db_path)
    draft = run_cycle(config, db, use_mock=True)
    assert draft is not None

    app = create_app(config, db)
    client = app.test_client()

    response = client.post(f"/draft/{draft.id}/approve", follow_redirects=False)
    stored = db.get_draft(draft.id)

    assert response.status_code == 302
    assert stored is not None
    assert stored.status == "exported"
    assert stored.published_at is None
    assert Path(stored.manual_export_path).exists()
    assert '"manual_export"' in stored.publish_response


def test_dashboard_hold_reject_and_regenerate_actions_update_draft(monkeypatch, tmp_path: Path) -> None:
    config = make_config(tmp_path)
    db = Database(config.db_path)
    draft = run_cycle(config, db, use_mock=True)
    assert draft is not None

    app = create_app(config, db)
    client = app.test_client()

    assert client.post(f"/draft/{draft.id}/hold").status_code == 302
    assert db.get_draft(draft.id).status == "held"

    original_caption = db.get_draft(draft.id).caption
    caption_response = client.post(f"/draft/{draft.id}/regenerate-caption", follow_redirects=True)
    regenerated = db.get_draft(draft.id)
    assert caption_response.status_code == 200
    assert b"description regenerated: variant 1" in caption_response.data
    assert "Source/courtesy:" not in regenerated.caption
    assert "Sources/courtesy:" not in regenerated.caption
    assert regenerated.caption != original_caption
    assert regenerated.log["caption_variant"] == 1

    def fake_regenerate_images(config, db, draft):
        draft.log["image_regenerated_at"] = "2026-07-30T06:00:00+00:00"
        db.update_draft(draft.id, log=draft.log)
        return draft, {"selected": []}

    monkeypatch.setattr("newsagent.dashboard.regenerate_draft_with_fresh_images", fake_regenerate_images)

    image_response = client.post(f"/draft/{draft.id}/regenerate-images", follow_redirects=True)
    assert image_response.status_code == 200
    assert b"images regenerated with 10 fresh stories" in image_response.data
    assert db.get_draft(draft.id).log["image_regenerated_at"]
    for story in db.get_draft(draft.id).stories:
        assert Path(story.slide_path).exists()

    assert client.post(f"/draft/{draft.id}/reject").status_code == 302
    assert db.get_draft(draft.id).status == "rejected"
