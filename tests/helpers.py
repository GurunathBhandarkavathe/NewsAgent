from __future__ import annotations

from pathlib import Path

from newsagent.config import Config


def make_config(tmp_path: Path, **overrides) -> Config:
    values = {
        "project_root": tmp_path,
        "data_dir": tmp_path / "data",
        "assets_dir": tmp_path / "assets",
        "db_path": tmp_path / "data" / "session-store.json",
        "enable_rss": False,
        "enable_gdelt": False,
        "enable_google_trends": False,
    }
    values.update(overrides)
    config = Config(**values)
    config.ensure_dirs()
    return config
