import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from heatshield import config  # noqa: E402


@pytest.fixture
def isolated_outputs(tmp_path, monkeypatch):
    """Point every *output* location of the pipeline at a temp dir.

    Bronze, the manifest and the trained model are read from the real repo
    (read-only); Silver/Gold/status/audit/quarantine/reports go to tmp_path.
    """
    from heatshield import pipeline

    out = tmp_path / "data"
    paths = {"SILVER": out / "silver", "GOLD": out / "gold", "STAGING": out / "_staging", "ARCHIVE": out / "_archive",
             "QUARANTINE": out / "quarantine", "AUDIT": out / "audit", "STATUS": out / "status",
             "REPORTS": tmp_path / "reports"}
    for name, p in paths.items():
        monkeypatch.setattr(config, name, p)
    monkeypatch.setattr(config, "DATA", out)
    monkeypatch.setattr(pipeline, "STATUS_FILE", paths["STATUS"] / "run_status.json")
    monkeypatch.setattr(pipeline, "HISTORY_FILE", paths["STATUS"] / "run_history.jsonl")
    monkeypatch.setattr(pipeline, "AUDIT_FILE", paths["AUDIT"] / "audit_log.jsonl")
    monkeypatch.setattr(pipeline, "LOCK_FILE", paths["STATUS"] / ".pipeline.lock")
    yield paths
    shutil.rmtree(tmp_path, ignore_errors=True)
