"""Integration tests on the real Bronze data, writing only to a temp folder."""
import hashlib
import json
from unittest import mock

import pandas as pd
import pytest

from heatshield import bronze, config, pipeline
from heatshield.drill import corrupt_values
from heatshield.model import MODEL_PATH

pytestmark = pytest.mark.skipif(not MODEL_PATH.exists(), reason="run `make -C src train` first")


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_successful_run_then_bad_runs_keep_trusted_data(isolated_outputs):
    rep = pipeline.run("data", fetch=False)
    assert rep["status"] == "success", rep.get("error")
    gold = config.GOLD / "heat_daily.csv"
    daily = pd.read_csv(gold)
    assert daily["row_id"].is_unique
    assert set(daily["city"]) == set(config.CITIES)
    assert (config.GOLD / "predictions.csv").exists()
    status = pipeline.read_status()
    assert status["last_success_run_id"] == rep["run_id"]
    assert set(status["freshness"]) == set(config.CITIES)
    trusted = sha(gold)

    # Corrupted values: quarantined by the agent, blocked by Gate 2.
    bad = pipeline.run("data", fetch=False, mutate=corrupt_values)
    assert bad["status"] == "failed_validation"
    assert not bad["gate2"]["passed"]
    assert sha(gold) == trusted
    assert list(config.QUARANTINE.glob(f"{bad['run_id']}/quarantined_records.csv"))
    status = pipeline.read_status()
    assert status["last_run_status"] == "failed_validation"
    assert status["serving_run_id"] == rep["run_id"]

    # Tampered raw file: rejected by Gate 1 before Silver is built.
    real = bronze.load_manifest
    def tampered():
        m = real()
        return {k: (dict(v, sha256="0" * 64) if "archive_karachi" in k else v) for k, v in m.items()}
    with mock.patch.object(bronze, "load_manifest", tampered):
        bad2 = pipeline.run("data", fetch=False)
    assert bad2["status"] == "failed_validation" and not bad2["gate1"]["passed"]
    assert sha(gold) == trusted

    audit = [json.loads(x) for x in (config.AUDIT / "audit_log.jsonl").read_text(encoding="utf-8").splitlines()]
    runs = {a["run_id"]: a["action"] for a in audit if a["stage"] == "pipeline"}
    assert runs == {rep["run_id"]: "success", bad["run_id"]: "failed_validation", bad2["run_id"]: "failed_validation"}


def test_gate1_rejects_unknown_wind_unit(tmp_path):
    src = next(config.BRONZE_OPEN_METEO.glob("forecast_karachi_*.json"))
    raw = json.loads(src.read_text(encoding="utf-8"))
    raw["hourly_units"]["wind_speed_10m"] = "furlongs/fortnight"
    p = tmp_path / src.name
    p.write_text(json.dumps(raw), encoding="utf-8")
    bf = bronze.BronzeFile(p, "open_meteo_forecast", "karachi", "20261019T141452Z")
    with mock.patch.object(bronze, "_verify_provenance", lambda *a: None):
        bronze.read_and_gate(bf, {})
    assert not bf.passed and bf.frame is None
    assert any(c["check"] == "wind_unit_known" and not c["passed"] for c in bf.checks)


def test_wind_converted_to_ms():
    manifest = bronze.load_manifest()
    om = next(f for f in bronze.discover() if f.source == "open_meteo_archive")
    bronze.read_and_gate(om, manifest)
    assert om.passed
    assert om.frame["wind_speed_ms"].max() < 40       # km/h values would be ~3.6x larger
