from __future__ import annotations

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

    assert "newsagent run-once --draft-id-file data/latest-draft-id.txt" in workflow
    assert "newsagent publish-latest" in workflow
    assert "--draft-id-file data/latest-draft-id.txt" in workflow
    assert "actions/deploy-pages" in workflow
