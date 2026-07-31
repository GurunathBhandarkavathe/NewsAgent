from __future__ import annotations

import re
from pathlib import Path

from newsagent.cli import resolve_requested_draft_id, write_draft_id_file
from newsagent.db import Database
from newsagent.pipeline import run_cycle

from helpers import make_config


def test_draft_id_file_points_publish_to_exact_generated_draft(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    db = Database(config.db_path)
    draft = run_cycle(config, db, use_mock=True)
    assert draft is not None

    draft_id_path = tmp_path / "data" / "latest-draft-id.txt"
    write_draft_id_file(str(draft_id_path), draft.id)

    assert resolve_requested_draft_id(db, None, str(draft_id_path)) == draft.id


def test_github_workflow_uses_exact_draft_id_before_publish() -> None:
    workflow = Path(".github/workflows/publish-instagram.yml").read_text(encoding="utf-8")

    assert "workflow_dispatch:" in workflow
    assert "schedule:" not in workflow
    assert "newsagent run-once --draft-id-file data/latest-draft-id.txt" in workflow
    assert "newsagent publish-latest" in workflow
    assert "--draft-id-file data/latest-draft-id.txt" in workflow
    assert "actions/deploy-pages" in workflow


def test_only_one_github_workflow_publishes_instagram_posts() -> None:
    workflows = Path(".github/workflows").glob("*.yml")
    publishers = [
        workflow
        for workflow in workflows
        if "newsagent publish-latest" in workflow.read_text(encoding="utf-8")
    ]

    assert publishers == [Path(".github/workflows/publish-instagram.yml")]


def test_cloudflare_scheduler_dispatches_publish_workflow_without_committed_token() -> None:
    scheduler_root = Path("deploy/cloudflare-scheduler")
    wrangler = (scheduler_root / "wrangler.toml").read_text(encoding="utf-8")
    worker = (scheduler_root / "src/index.js").read_text(encoding="utf-8")

    assert 'crons = [ "30 0,3,6,9,12,15,18,21 * * *" ]' in wrangler
    assert 'GITHUB_WORKFLOW_ID = "publish-instagram.yml"' in wrangler
    assert 'required = [ "GITHUB_TOKEN" ]' in wrangler
    assert "/actions/workflows/" in worker
    assert "/dispatches" in worker
    assert "workflow_dispatch_sent" in worker
    assert not re.search(r"gh[pousr]_[A-Za-z0-9_]{20,}", wrangler + worker)
