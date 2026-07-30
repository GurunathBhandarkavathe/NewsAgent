from __future__ import annotations

import argparse
import json
import threading
from pathlib import Path

from .brand import production_checks, profile_fields, publish_ready
from .config import load_config
from .dashboard import create_app
from .db import Database
from .meta import check_meta_connection
from .pipeline import run_cycle, worker_loop
from .publisher import Publisher
from .utils import utcnow


def main() -> None:
    parser = argparse.ArgumentParser(prog="newsagent")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_once = subparsers.add_parser("run-once", help="Create one draft cycle.")
    run_once.add_argument("--mock", action="store_true", help="Use deterministic mocked news items.")
    run_once.add_argument("--draft-id-file", help="Write the created draft id to this file. Empty when no draft is created.")

    serve = subparsers.add_parser("serve", help="Start the approval dashboard.")
    serve.add_argument("--debug", action="store_true")

    worker = subparsers.add_parser("worker", help="Run the scheduler loop.")
    worker.add_argument("--mock", action="store_true")
    worker.add_argument("--immediate", action="store_true", help="Run a cycle immediately before waiting.")

    combined = subparsers.add_parser("run", help="Run dashboard and scheduler in one process.")
    combined.add_argument("--mock", action="store_true")
    combined.add_argument("--immediate", action="store_true")

    production = subparsers.add_parser("production", help="Run the Samachar Bharat production pipeline.")
    production.add_argument("--no-immediate", action="store_true", help="Wait until the next 3-hour IST slot before first run.")

    doctor = subparsers.add_parser("doctor", help="Check production readiness.")
    doctor.add_argument("--strict", action="store_true", help="Exit non-zero when publish credentials are incomplete.")

    subparsers.add_parser("test-meta", help="Test Meta publishing credentials without posting.")

    publish_latest = subparsers.add_parser("publish-latest", help="Publish a stored draft through Meta.")
    publish_latest.add_argument("--draft-id", help="Publish this exact draft id.")
    publish_latest.add_argument("--draft-id-file", help="Read the draft id from this file.")
    publish_latest.add_argument("--public-asset-base-url", help="Override PUBLIC_ASSET_BASE_URL for this publish.")
    publish_latest.add_argument("--allow-export", action="store_true", help="Allow manual export fallback instead of failing.")

    subparsers.add_parser("list-drafts", help="List recent drafts.")

    args = parser.parse_args()
    config = load_config()
    db = Database(config.db_path)

    if args.command == "run-once":
        draft = run_cycle(config, db, use_mock=args.mock)
        if args.draft_id_file:
            write_draft_id_file(args.draft_id_file, draft.id if draft else "")
        if draft:
            print(f"created draft {draft.id} with {len(draft.stories)} slides")
        else:
            print("no draft created; not enough fresh stories")
        return

    if args.command == "serve":
        app = create_app(config, db)
        app.run(host=config.dashboard_host, port=config.dashboard_port, debug=args.debug)
        return

    if args.command == "worker":
        worker_loop(config, use_mock=args.mock, immediate=args.immediate)
        return

    if args.command == "run":
        start_dashboard(config, db)
        worker_loop(config, use_mock=args.mock, immediate=args.immediate)
        return

    if args.command == "production":
        print_brand_summary(config)
        print_checks(config)
        start_dashboard(config, db)
        worker_loop(config, use_mock=False, immediate=not args.no_immediate)
        return

    if args.command == "doctor":
        print_brand_summary(config)
        checks = production_checks(config)
        print_checks(config)
        has_blocks = any(check.blocks_publish for check in checks)
        if args.strict and (has_blocks or not publish_ready(config)):
            raise SystemExit(1)
        return

    if args.command == "test-meta":
        result = check_meta_connection(config, sample_slide_path=latest_slide_path(db))
        for check in result.checks:
            status = "OK" if check["ok"] else "FAIL"
            detail = f": {check['detail']}" if check["detail"] else ""
            print(f"[{status}] {check['name']}{detail}")
        if result.sample_asset_url:
            print(f"sample asset URL: {result.sample_asset_url}")
        raise SystemExit(0 if result.ok else 1)

    if args.command == "publish-latest":
        if args.public_asset_base_url:
            config.public_asset_base_url = args.public_asset_base_url.strip()
        draft_id = resolve_requested_draft_id(db, args.draft_id, args.draft_id_file)
        if not draft_id:
            print("no draft id available to publish")
            raise SystemExit(1)
        draft = db.get_draft(draft_id)
        if not draft:
            print(f"draft not found: {draft_id}")
            raise SystemExit(1)
        result = Publisher(config).publish(draft)
        db.update_draft(
            draft.id,
            status=result.status,
            manual_export_path=result.manual_export_path,
            published_at=utcnow() if result.status == "published" else None,
            publish_response=json.dumps(result.response, sort_keys=True),
        )
        print(f"{result.status}: {result.message}")
        if result.manual_export_path:
            print(f"manual export: {result.manual_export_path}")
        if result.status != "published" and not args.allow_export:
            raise SystemExit(1)
        return

    if args.command == "list-drafts":
        for row in db.list_drafts():
            print(f"{row['created_at']}  {row['status']:<10}  {row['id']}")
        return


def start_dashboard(config, db: Database) -> None:
    app = create_app(config, db)
    thread = threading.Thread(
        target=lambda: app.run(host=config.dashboard_host, port=config.dashboard_port, debug=False, use_reloader=False),
        daemon=True,
    )
    thread.start()
    print(f"dashboard running on http://{config.dashboard_host}:{config.dashboard_port}")


def print_brand_summary(config) -> None:
    profile = profile_fields(config)
    print(f"{profile['name']} {profile['handle']}")
    print(profile["tagline"])


def print_checks(config) -> None:
    for check in production_checks(config):
        print(f"[{check.status.upper()}] {check.name}: {check.detail}")
    if publish_ready(config):
        print("[OK] Meta publishing: ready after dashboard approval")
    else:
        print("[WARN] Meta publishing: approvals will export a manual posting package")


def latest_slide_path(db: Database) -> str:
    for row in db.list_drafts(limit=1):
        draft = db.get_draft(row["id"])
        if draft and draft.stories:
            return draft.stories[0].slide_path
    return ""


def resolve_requested_draft_id(db: Database, draft_id: str | None, draft_id_file: str | None) -> str:
    if draft_id:
        return draft_id.strip()
    if draft_id_file:
        path = Path(draft_id_file)
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
        return ""
    for row in db.list_drafts(limit=1):
        return str(row["id"])
    return ""


def write_draft_id_file(draft_id_file: str, draft_id: str) -> None:
    path = Path(draft_id_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(draft_id, encoding="utf-8")


if __name__ == "__main__":
    main()
