"""Tests for Member 3's entry point src/quality_agent.py."""
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

SPEC = importlib.util.spec_from_file_location("member3_quality_agent",
                                              Path(__file__).resolve().parents[1] / "src" / "quality_agent.py")
m3 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m3)


@pytest.fixture
def outputs(tmp_path, monkeypatch):
    monkeypatch.setattr(m3, "LOG_FILE", tmp_path / "audit.jsonl")
    monkeypatch.setattr(m3, "REPORT_FILE", tmp_path / "validation_report.json")
    monkeypatch.setattr(m3, "QUARANTINE_DIR", tmp_path / "quarantine")
    return tmp_path


def open_meteo_csv(path, n=240, bad=()):
    t = 35 + 6 * np.sin(2 * np.pi * np.arange(n) / 24)
    df = pd.DataFrame({"time": pd.date_range("2025-05-01", periods=n, freq="h").strftime("%Y-%m-%dT%H:%M"),
                       "temperature_2m": t, "relative_humidity_2m": 12.0, "dew_point_2m": 2.0, "wind_speed_10m": 10.8})
    for i in bad:
        df.loc[i, "temperature_2m"] = 999.0
    df.loc[50, "relative_humidity_2m"] = np.nan
    df.to_csv(path, index=False)
    return path


def test_file_check_fixes_without_inventing_values(outputs):
    out = m3.run_quality_checks(str(open_meteo_csv(outputs / "in.csv", bad=[100])))
    assert out is not None
    assert out.loc[50, "humidity_pct"] == pytest.approx(12.0)   # interpolated from neighbours, not a fixed 50 %
    assert out.loc[50, "qc_flag"] == "filled_interp"
    assert out["wind_speed_ms"].iloc[0] == pytest.approx(3.0)    # km/h converted to m/s
    rep = json.loads((outputs / "validation_report.json").read_text())
    assert rep["status"] == "PASSED" and rep["quarantined_records"] == 1
    assert list((outputs / "quarantine").glob("*/quarantined_records.csv"))
    assert (outputs / "audit.jsonl").read_text().count("quality_gate") == 1


def test_file_check_fails_gate_on_bad_data(outputs):
    out = m3.run_quality_checks(str(open_meteo_csv(outputs / "bad.csv", bad=range(0, 240, 3))))
    assert out is None
    assert json.loads((outputs / "validation_report.json").read_text())["status"] == "FAILED"


def test_missing_file_is_a_clear_error(outputs):
    with pytest.raises(FileNotFoundError):
        m3.run_quality_checks(str(outputs / "nope.csv"))
