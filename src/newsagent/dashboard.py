from __future__ import annotations

import json
import secrets
from pathlib import Path
from urllib.parse import urlencode

from flask import Flask, abort, redirect, render_template_string, request, send_from_directory, url_for

from .brand import production_checks, profile_fields, publish_ready
from .caption import build_caption
from .config import Config
from .db import Database
from .env_store import save_env_values
from .image_render import render_draft_images
from .meta import check_meta_connection
from .pipeline import regenerate_draft_with_fresh_images, run_cycle, write_draft_files
from .publisher import Publisher
from .utils import ensure_relative_to, utcnow


def create_app(config: Config, db: Database | None = None) -> Flask:
    db = db or Database(config.db_path)
    app = Flask(__name__)

    def token_query() -> str:
        return f"?token={config.dashboard_token}" if config.dashboard_token else ""

    def redirect_with_notice(endpoint: str, notice: str, **values):
        target = url_for(endpoint, **values)
        params: dict[str, str] = {}
        if config.dashboard_token:
            params["token"] = config.dashboard_token
        params["notice"] = notice
        return redirect(target + "?" + urlencode(params))

    def check_auth() -> None:
        if not config.dashboard_token:
            return
        provided = request.values.get("token") or request.headers.get("X-NewsAgent-Token", "")
        if provided != config.dashboard_token:
            abort(403)

    def asset_url(slide_path: str) -> str:
        relative = ensure_relative_to(Path(slide_path), config.assets_dir)
        params: dict[str, str] = {}
        if config.dashboard_token:
            params["token"] = config.dashboard_token
        path = Path(slide_path)
        if path.exists():
            params["v"] = str(int(path.stat().st_mtime))
        suffix = f"?{urlencode(params)}" if params else ""
        return url_for("assets", filename=relative) + suffix

    @app.get("/")
    def index():
        check_auth()
        drafts = [draft for row in db.list_drafts(limit=50) if (draft := db.get_draft(row["id"]))]
        return render_template_string(
            INDEX_TEMPLATE,
            drafts=drafts,
            asset_url=asset_url,
            config=config,
            token=config.dashboard_token,
            token_query=token_query(),
        )

    @app.get("/brand")
    def brand_page():
        check_auth()
        return render_template_string(
            BRAND_TEMPLATE,
            config=config,
            profile=profile_fields(config),
            checks=production_checks(config),
            publish_ready=publish_ready(config),
            token_query=token_query(),
        )

    @app.get("/setup/meta")
    def meta_setup():
        check_auth()
        return render_meta_setup()

    @app.post("/setup/meta")
    def save_meta_setup():
        check_auth()
        values = meta_values_from_form(config)
        env_path = config.project_root / ".env"
        save_env_values(env_path, values)
        apply_meta_values(config, values)
        return redirect_with_notice("meta_setup", "Meta publishing settings saved")

    @app.post("/setup/meta/test")
    def test_meta_setup():
        check_auth()
        values = meta_values_from_form(config)
        apply_meta_values(config, values)
        sample = latest_slide_path(db)
        result = check_meta_connection(config, sample_slide_path=sample)
        return render_meta_setup(test_result=result)

    def render_meta_setup(test_result=None):
        public_token = config.public_asset_token or secrets.token_urlsafe(24)
        suggested_base = f"https://YOUR-HTTPS-HOST/public-assets/{public_token}/"
        return render_template_string(
            META_SETUP_TEMPLATE,
            config=config,
            test_result=test_result,
            meta_token_configured=bool(config.meta_access_token),
            public_token=public_token,
            suggested_base=suggested_base,
            token=config.dashboard_token,
            token_query=token_query(),
            notice=request.args.get("notice", ""),
        )

    @app.get("/draft/<draft_id>")
    def draft_detail(draft_id: str):
        check_auth()
        draft = db.get_draft(draft_id)
        if not draft:
            abort(404)
        return render_template_string(
            DETAIL_TEMPLATE,
            draft=draft,
            asset_url=asset_url,
            config=config,
            token=config.dashboard_token,
            token_query=token_query(),
            log_json=json.dumps(draft.log, indent=2),
            notice=request.args.get("notice", ""),
            image_regenerated_at=draft.log.get("image_regenerated_at", ""),
            caption_variant=draft.log.get("caption_variant", 0),
        )

    @app.post("/run-cycle")
    def run_cycle_route():
        check_auth()
        use_mock = request.form.get("mock") == "true"
        draft = run_cycle(config, db, use_mock=use_mock)
        if draft:
            return redirect(url_for("draft_detail", draft_id=draft.id) + token_query())
        return redirect(url_for("index") + token_query())

    @app.post("/draft/<draft_id>/approve")
    def approve(draft_id: str):
        check_auth()
        draft = db.get_draft(draft_id)
        if not draft:
            abort(404)
        result = Publisher(config).publish(draft)
        db.update_draft(
            draft.id,
            status=result.status,
            manual_export_path=result.manual_export_path,
            published_at=utcnow() if result.status == "published" else None,
            publish_response=json.dumps(result.response, sort_keys=True),
        )
        db.log_event("info", "Draft approval processed.", {"draft_id": draft.id, "status": result.status})
        return redirect_with_notice("draft_detail", f"approval processed: {result.status}", draft_id=draft.id)

    @app.post("/draft/<draft_id>/reject")
    def reject(draft_id: str):
        check_auth()
        db.update_draft(draft_id, status="rejected")
        db.log_event("info", "Draft rejected.", {"draft_id": draft_id})
        return redirect_with_notice("draft_detail", "draft rejected", draft_id=draft_id)

    @app.post("/draft/<draft_id>/hold")
    def hold(draft_id: str):
        check_auth()
        db.update_draft(draft_id, status="held")
        db.log_event("info", "Draft held.", {"draft_id": draft_id})
        return redirect_with_notice("draft_detail", "draft held", draft_id=draft_id)

    @app.post("/draft/<draft_id>/regenerate-caption")
    def regenerate_caption(draft_id: str):
        check_auth()
        draft = db.get_draft(draft_id)
        if not draft:
            abort(404)
        variant = int(draft.log.get("caption_variant", 0)) + 1
        draft.caption = build_caption(
            draft.stories,
            variant=variant,
            brand_name=config.brand_name,
            brand_handle=config.brand_handle,
            brand_tagline=config.brand_tagline,
        )
        draft.log["caption_variant"] = variant
        draft.log["caption_regenerated_at"] = utcnow().isoformat()
        write_draft_files(draft, config)
        db.update_draft(draft.id, caption=draft.caption, log=draft.log)
        db.log_event("info", "Draft Instagram description regenerated.", {"draft_id": draft.id, "variant": variant})
        return redirect_with_notice("draft_detail", f"description regenerated: variant {variant}", draft_id=draft.id)

    @app.post("/draft/<draft_id>/regenerate-images")
    def regenerate_images(draft_id: str):
        check_auth()
        draft = db.get_draft(draft_id)
        if not draft:
            abort(404)
        refreshed, refresh_log = regenerate_draft_with_fresh_images(config, db, draft)
        if not refreshed:
            draft.log["image_regeneration_failed_at"] = utcnow().isoformat()
            draft.log["image_regeneration"] = refresh_log
            db.update_draft(draft.id, log=draft.log)
            db.log_event("warning", "Draft image regeneration could not find enough fresh stories.", {"draft_id": draft.id})
            return redirect_with_notice("draft_detail", "not enough fresh real-image stories found", draft_id=draft.id)
        return redirect_with_notice("draft_detail", f"images regenerated with {len(refreshed.stories)} fresh stories", draft_id=draft.id)

    @app.get("/assets/<path:filename>")
    def assets(filename: str):
        check_auth()
        return send_from_directory(config.assets_dir, filename)

    @app.get("/public-assets/<asset_token>/<path:filename>")
    def public_assets(asset_token: str, filename: str):
        if not config.public_asset_token or not secrets.compare_digest(asset_token, config.public_asset_token):
            abort(404)
        return send_from_directory(config.assets_dir, filename)

    return app


def meta_values_from_form(config: Config) -> dict[str, str]:
    public_asset_token = request.form.get("public_asset_token", "").strip() or config.public_asset_token or secrets.token_urlsafe(24)
    values = {
        "META_GRAPH_VERSION": request.form.get("meta_graph_version", config.meta_graph_version).strip() or "v26.0",
        "META_API_HOST": Config._normalize_meta_api_host(request.form.get("meta_api_host", config.meta_api_host)),
        "INSTAGRAM_BUSINESS_ACCOUNT_ID": request.form.get("instagram_business_account_id", "").strip(),
        "PUBLIC_ASSET_BASE_URL": request.form.get("public_asset_base_url", "").strip(),
        "PUBLIC_ASSET_TOKEN": public_asset_token,
    }
    meta_access_token = request.form.get("meta_access_token", "").strip()
    values["META_ACCESS_TOKEN"] = meta_access_token or config.meta_access_token
    return values


def apply_meta_values(config: Config, values: dict[str, str]) -> None:
    config.meta_graph_version = values["META_GRAPH_VERSION"].strip().strip("/") or "v26.0"
    config.meta_api_host = Config._normalize_meta_api_host(values.get("META_API_HOST", ""))
    config.instagram_business_account_id = values["INSTAGRAM_BUSINESS_ACCOUNT_ID"]
    config.public_asset_base_url = values["PUBLIC_ASSET_BASE_URL"]
    config.public_asset_token = values["PUBLIC_ASSET_TOKEN"]
    if values["META_ACCESS_TOKEN"]:
        config.meta_access_token = values["META_ACCESS_TOKEN"]


def latest_slide_path(db: Database) -> str:
    for row in db.list_drafts(limit=1):
        draft = db.get_draft(row["id"])
        if draft and draft.stories:
            return draft.stories[0].slide_path
    return ""


BASE_CSS = """
body { margin: 0; font-family: Arial, sans-serif; background: #f5f5f0; color: #1d2329; }
header { background: #192027; color: #fff; padding: 22px 32px; display: flex; align-items: center; justify-content: space-between; gap: 20px; }
header h1 { margin: 0; }
header p { margin: 6px 0 0; color: #cbd7de; }
a { color: #1f6f8b; text-decoration: none; }
main { max-width: 1180px; margin: 0 auto; padding: 28px; }
.toolbar { display: flex; gap: 12px; flex-wrap: wrap; align-items: center; }
button, .button { border: 0; border-radius: 6px; padding: 10px 14px; background: #1f6f8b; color: #fff; cursor: pointer; font-weight: 700; }
button.secondary { background: #59636e; }
button.danger { background: #b33a3a; }
button.warn { background: #ad6a18; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 18px; }
.card { background: #fff; border: 1px solid #dde0dc; border-radius: 8px; padding: 16px; }
.draft-card { display: flex; flex-direction: column; gap: 12px; }
.draft-card h2 { font-size: 18px; line-height: 1.25; margin: 0; overflow-wrap: anywhere; }
.preview-strip { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
.preview-strip img { width: 100%; aspect-ratio: 4 / 5; object-fit: cover; border-radius: 6px; border: 1px solid #d7d9d4; background: #eceee8; }
.status { display: inline-block; border-radius: 999px; padding: 4px 10px; background: #e7efe8; color: #24533a; font-size: 12px; font-weight: 700; text-transform: uppercase; }
.slides { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; }
.slides img { width: 100%; border-radius: 8px; border: 1px solid #d7d9d4; }
pre, textarea { width: 100%; box-sizing: border-box; white-space: pre-wrap; background: #fff; border: 1px solid #d7d9d4; border-radius: 8px; padding: 14px; }
.story { border-top: 1px solid #dde0dc; padding: 14px 0; }
.muted { color: #66707a; }
.notice { background: #e7f3ef; border: 1px solid #8ac4ad; color: #214b3c; border-radius: 8px; padding: 12px 14px; margin: 0 0 18px; font-weight: 700; }
.meta-row { display: flex; gap: 16px; flex-wrap: wrap; color: #66707a; font-size: 14px; }
.brand-hero { display: grid; grid-template-columns: minmax(0, 1.2fr) minmax(280px, 0.8fr); gap: 20px; align-items: stretch; }
.brand-title { font-size: 56px; line-height: 1; margin: 0 0 10px; }
.brand-handle { color: #1f6f8b; font-weight: 700; }
.profile-field { display: grid; gap: 4px; border-top: 1px solid #dde0dc; padding: 14px 0; }
.profile-field:first-child { border-top: 0; padding-top: 0; }
.profile-field span { color: #66707a; font-size: 13px; font-weight: 700; text-transform: uppercase; }
.check { display: flex; justify-content: space-between; gap: 12px; border-top: 1px solid #dde0dc; padding: 12px 0; }
.check:first-child { border-top: 0; }
.check strong { overflow-wrap: anywhere; }
.check-status { border-radius: 999px; padding: 4px 9px; color: #fff; font-size: 12px; font-weight: 700; text-transform: uppercase; align-self: flex-start; }
.check-status.ok { background: #2d7d50; }
.check-status.warn { background: #ad6a18; }
.check-status.block { background: #b33a3a; }
.form-grid { display: grid; gap: 16px; max-width: 860px; }
.form-field { display: grid; gap: 6px; }
.form-field label { font-weight: 700; }
.form-field input, .form-field select { box-sizing: border-box; width: 100%; border: 1px solid #c9cec8; border-radius: 6px; padding: 11px 12px; font: inherit; background: #fff; }
.result-list { display: grid; gap: 10px; }
.result-row { display: flex; justify-content: space-between; gap: 16px; border-top: 1px solid #dde0dc; padding: 10px 0; }
.result-row:first-child { border-top: 0; }
@media (max-width: 760px) { .brand-hero { grid-template-columns: 1fr; } .brand-title { font-size: 42px; } header { align-items: flex-start; flex-direction: column; } }
"""


INDEX_TEMPLATE = """
<!doctype html>
<html>
<head>
  <title>{{ config.brand_name }} Drafts</title>
  <style>{{ css }}</style>
</head>
<body>
  <header>
    <div>
      <h1>{{ config.brand_name }} Drafts</h1>
      <p>{{ config.brand_tagline }}</p>
    </div>
    <div class="toolbar">
      <a class="button secondary" href="/brand{{ token_query }}">Brand Page</a>
      <a class="button secondary" href="/setup/meta{{ token_query }}">Meta Setup</a>
      <form class="toolbar" method="post" action="/run-cycle{{ token_query }}">
        {% if token %}<input type="hidden" name="token" value="{{ token }}">{% endif %}
        <button type="submit">Run Real Cycle</button>
        <button class="secondary" type="submit" name="mock" value="true">Run Mock Cycle</button>
      </form>
    </div>
  </header>
  <main>
    <div class="grid">
      {% for draft in drafts %}
      <div class="card draft-card">
        <a class="preview-strip" href="/draft/{{ draft.id }}{{ token_query }}" aria-label="Open draft {{ draft.id }}">
          {% for story in draft.stories[:3] %}
            <img src="{{ asset_url(story.slide_path) }}" alt="{{ story.title }}">
          {% endfor %}
        </a>
        <p><span class="status">{{ draft.status }}</span></p>
        <h2><a href="/draft/{{ draft.id }}{{ token_query }}">{{ draft.id }}</a></h2>
        <p class="muted">{{ draft.created_at }}</p>
      </div>
      {% else %}
      <div class="card">No drafts yet.</div>
      {% endfor %}
    </div>
  </main>
</body>
</html>
""".replace("{{ css }}", BASE_CSS)


BRAND_TEMPLATE = """
<!doctype html>
<html>
<head>
  <title>{{ config.brand_name }} Brand</title>
  <style>{{ css }}</style>
</head>
<body>
  <header>
    <div>
      <h1>{{ config.brand_name }} Brand</h1>
      <p>{{ config.brand_tagline }}</p>
    </div>
    <div class="toolbar">
      <a class="button secondary" href="/setup/meta{{ token_query }}">Meta Setup</a>
      <a class="button" href="/{{ token_query }}">All Drafts</a>
    </div>
  </header>
  <main>
    <div class="brand-hero">
      <section class="card">
        <h2 class="brand-title">{{ profile.name }}</h2>
        <p class="brand-handle">{{ profile.handle }}</p>
        <div class="profile-field"><span>Bio</span><strong>{{ profile.bio }}</strong></div>
        <div class="profile-field"><span>Category</span><strong>{{ profile.category }}</strong></div>
        <div class="profile-field"><span>Signature</span><strong>{{ profile.caption_signature }}</strong></div>
      </section>
      <section class="card">
        <h2>Production</h2>
        {% for check in checks %}
          <div class="check">
            <div>
              <strong>{{ check.name }}</strong>
              <div class="muted">{{ check.detail }}</div>
            </div>
            <span class="check-status {{ check.status }}">{{ check.status }}</span>
          </div>
        {% endfor %}
      </section>
    </div>
  </main>
</body>
</html>
""".replace("{{ css }}", BASE_CSS)


META_SETUP_TEMPLATE = """
<!doctype html>
<html>
<head>
  <title>Meta Setup</title>
  <style>{{ css }}</style>
</head>
<body>
  <header>
    <div>
      <h1>Meta Publishing Setup</h1>
      <p>{{ config.brand_name }} · {{ config.brand_handle }}</p>
    </div>
    <a class="button" href="/{{ token_query }}">All Drafts</a>
  </header>
  <main>
    {% if notice %}
      <div class="notice">{{ notice }}</div>
    {% endif %}

    <section class="card">
      <h2>What To Paste Here</h2>
      <p class="muted">Use this after your Instagram page is Professional, linked to a Facebook Page, and your Meta developer app has Content Publishing access.</p>
      <form class="form-grid" method="post" action="/setup/meta{{ token_query }}">
        {% if token %}<input type="hidden" name="token" value="{{ token }}">{% endif %}
        <div class="form-field">
          <label for="meta_graph_version">Meta Graph API Version</label>
          <input id="meta_graph_version" name="meta_graph_version" value="{{ config.meta_graph_version }}">
        </div>
        <div class="form-field">
          <label for="meta_api_host">Meta API Host</label>
          <select id="meta_api_host" name="meta_api_host">
            <option value="" {% if not config.meta_api_host %}selected{% endif %}>Auto detect from token</option>
            <option value="graph.instagram.com" {% if config.meta_api_host == 'graph.instagram.com' %}selected{% endif %}>graph.instagram.com · Instagram Login / IGAA token</option>
            <option value="graph.facebook.com" {% if config.meta_api_host == 'graph.facebook.com' %}selected{% endif %}>graph.facebook.com · Facebook Login / EAA token</option>
          </select>
          <div class="muted">Current lookup endpoint: {{ config.meta_api_base_url }}/{{ config.instagram_business_account_id or 'YOUR_IG_USER_ID' }}</div>
        </div>
        <div class="form-field">
          <label for="instagram_business_account_id">Instagram Business/Creator Account ID</label>
          <input id="instagram_business_account_id" name="instagram_business_account_id" value="{{ config.instagram_business_account_id }}" placeholder="17890000000000000">
        </div>
        <div class="form-field">
          <label for="meta_access_token">Meta Access Token</label>
          <input id="meta_access_token" name="meta_access_token" type="password" placeholder="{% if meta_token_configured %}Token is configured; leave blank to keep it{% else %}Paste token{% endif %}">
        </div>
        <div class="form-field">
          <label for="public_asset_token">Public Asset Token</label>
          <input id="public_asset_token" name="public_asset_token" value="{{ public_token }}">
        </div>
        <div class="form-field">
          <label for="public_asset_base_url">Public HTTPS Asset Base URL</label>
          <input id="public_asset_base_url" name="public_asset_base_url" value="{{ config.public_asset_base_url }}" placeholder="{{ suggested_base }}">
          <div class="muted">Use this format when your tunnel/domain points to this dashboard: {{ suggested_base }}</div>
        </div>
        <div class="toolbar">
          <button type="submit">Save Settings</button>
        </div>
      </form>
    </section>

    <section class="card">
      <h2>Test Without Posting</h2>
      <form method="post" action="/setup/meta/test{{ token_query }}">
        {% if token %}<input type="hidden" name="token" value="{{ token }}">{% endif %}
        <input type="hidden" name="meta_graph_version" value="{{ config.meta_graph_version }}">
        <input type="hidden" name="meta_api_host" value="{{ config.meta_api_host }}">
        <input type="hidden" name="instagram_business_account_id" value="{{ config.instagram_business_account_id }}">
        <input type="hidden" name="public_asset_base_url" value="{{ config.public_asset_base_url }}">
        <input type="hidden" name="public_asset_token" value="{{ public_token }}">
        <button class="secondary" type="submit">Test Connection</button>
      </form>
      {% if test_result %}
        <div class="result-list">
          {% for check in test_result.checks %}
            <div class="result-row">
              <strong>{{ check.name }}</strong>
              <span class="check-status {{ 'ok' if check.ok else 'block' }}">{{ 'ok' if check.ok else 'needs work' }}</span>
            </div>
            {% if check.detail %}<div class="muted">{{ check.detail }}</div>{% endif %}
          {% endfor %}
        </div>
        {% if test_result.sample_asset_url %}
          <p class="muted">Sample asset URL: {{ test_result.sample_asset_url }}</p>
        {% endif %}
      {% endif %}
    </section>

    <section class="card">
      <h2>Required Meta Steps</h2>
      <p>1. Set Instagram to Professional. 2. Link it to a Facebook Page. 3. Create/configure a Meta developer app. 4. Generate a token with Instagram publishing permissions. 5. Expose this app through HTTPS and use the public-assets URL above.</p>
    </section>
  </main>
</body>
</html>
""".replace("{{ css }}", BASE_CSS)


DETAIL_TEMPLATE = """
<!doctype html>
<html>
<head>
  <title>{{ draft.id }}</title>
  <style>{{ css }}</style>
</head>
<body>
  <header>
    <div>
      <h1>{{ config.brand_name }} Draft</h1>
      <p>{{ draft.id }} · <span class="status">{{ draft.status }}</span></p>
    </div>
    <div class="toolbar">
      <a class="button secondary" href="/brand{{ token_query }}">Brand Page</a>
      <a class="button" href="/{{ token_query }}">All Drafts</a>
    </div>
  </header>
  <main>
    {% if notice %}
      <div class="notice">{{ notice }}</div>
    {% endif %}
    <div class="toolbar">
      <form method="post" action="/draft/{{ draft.id }}/approve{{ token_query }}">
        {% if token %}<input type="hidden" name="token" value="{{ token }}">{% endif %}
        <button type="submit">Approve</button>
      </form>
      <form method="post" action="/draft/{{ draft.id }}/hold{{ token_query }}">
        {% if token %}<input type="hidden" name="token" value="{{ token }}">{% endif %}
        <button class="warn" type="submit">Hold</button>
      </form>
      <form method="post" action="/draft/{{ draft.id }}/reject{{ token_query }}">
        {% if token %}<input type="hidden" name="token" value="{{ token }}">{% endif %}
        <button class="danger" type="submit">Reject</button>
      </form>
      <form method="post" action="/draft/{{ draft.id }}/regenerate-caption{{ token_query }}">
        {% if token %}<input type="hidden" name="token" value="{{ token }}">{% endif %}
        <button class="secondary" type="submit">Regenerate Description</button>
      </form>
      <form method="post" action="/draft/{{ draft.id }}/regenerate-images{{ token_query }}">
        {% if token %}<input type="hidden" name="token" value="{{ token }}">{% endif %}
        <button class="secondary" type="submit">Regenerate Images</button>
      </form>
    </div>

    {% if draft.manual_export_path %}
      <p class="card">Manual export: {{ draft.manual_export_path }}</p>
    {% endif %}
    {% if draft.publish_response %}
      <pre>{{ draft.publish_response }}</pre>
    {% endif %}
    <div class="meta-row">
      <span>Description variant: {{ caption_variant }}</span>
      {% if image_regenerated_at %}<span>Images regenerated: {{ image_regenerated_at }}</span>{% endif %}
    </div>

    <h2>Slides</h2>
    <div class="slides">
      {% for story in draft.stories %}
        <img src="{{ asset_url(story.slide_path) }}" alt="{{ story.title }}">
      {% endfor %}
    </div>

    <h2>Instagram Description</h2>
    <pre>{{ draft.caption }}</pre>

    <h2>Stories</h2>
    {% for story in draft.stories %}
      <div class="story">
        <strong>{{ story.category.replace("_", " ").title() }}</strong>
        <p>{{ story.title }}</p>
        <p><a href="{{ story.url }}">{{ story.source }}</a></p>
        <p class="muted">Rights: {{ story.rights_risk }}</p>
      </div>
    {% endfor %}

    <h2>Cycle Log</h2>
    <pre>{{ log_json }}</pre>
  </main>
</body>
</html>
""".replace("{{ css }}", BASE_CSS)
