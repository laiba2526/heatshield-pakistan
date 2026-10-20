"""Member 3 - Data Quality Agent & automation entry point.

Two ways to use it:

1. Full automated run (what ``make -C src data`` / ``make -C src update`` do)::

       python src/quality_agent.py            # rebuild from Bronze, both quality gates, promote if valid
       python src/quality_agent.py --update   # hourly refresh: fetch latest Open-Meteo data first

   Runs Quality Gate 1 (raw files), the Data Quality Agent (fix / fill / flag /
   quarantine), builds Silver and Gold, runs Quality Gate 2 and only then
   replaces the trusted data. If a gate fails, the last trusted dataset is kept.

2. Check one file (any hourly CSV or parquet with a timestamp column)::

       python src/quality_agent.py --file my_data.csv

   Accepts Open-Meteo column names (``temperature_2m``, ``relative_humidity_2m``,
   ...) or Silver names (``temperature_c``, ``humidity_pct``, ...).

Outputs
-------
* ``reports/validation_report.json`` - summary of the latest check (gates,
  agent actions, freshness, status PASSED / FAILED)
* ``data/audit/audit_log.jsonl``     - every rule, action and gate decision
* ``data/quarantine/<run_id>/``      - quarantined records with original values
* ``data/status/run_status.json``    - last run, last successful run, freshness

The checking rules live in ``src/heatshield/quality.py`` and the gates
in ``src/heatshield/pipeline.py``; this file is the command-line front end.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from heatshield import config, pipeline  # noqa: E402
from heatshield.quality import DataQualityAgent  # noqa: E402

LOG_FILE = config.AUDIT / "audit_log.jsonl"
REPORT_FILE = config.REPORTS / "validation_report.json"
QUARANTINE_DIR = config.QUARANTINE
GOLD_FILE = config.GOLD / "heat_daily.csv"          # always the last trusted Gold table

COLUMN_MAP = {
    "temperature_2m": "temperature_c", "temperature": "temperature_c", "t2m": "temperature_c",
    "relative_humidity_2m": "humidity_pct", "relativehumidity_2m": "humidity_pct", "humidity": "humidity_pct",
    "rh2m": "humidity_pct", "dew_point_2m": "dew_point_c", "dew_point": "dew_point_c", "t2mdew": "dew_point_c",
    "wind_speed_10m": "wind_speed_kmh", "wind_speed": "wind_speed_ms", "ws10m": "wind_speed_ms",
    "timestamp": "timestamp_utc", "time": "timestamp_utc", "date": "timestamp_utc",
}


def log_audit(record_id, check_name, action_taken, reason, run_id: str = "manual") -> None:
    """Append one entry to the shared audit log (same file the pipeline uses)."""
    pipeline.append_jsonl(LOG_FILE, [{
        "run_id": run_id, "ts_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "stage": "member3_cli", "rule": check_name, "action": action_taken,
        "record_id": str(record_id), "reason": reason,
    }])


def _write_report(report: dict) -> None:
    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text(json.dumps(pipeline._jsonable(report), indent=2), encoding="utf-8")


def _standardise(df: pd.DataFrame) -> pd.DataFrame:
    df = df.rename(columns={c: COLUMN_MAP.get(c.strip().lower(), c.strip().lower()) for c in df.columns})
    if "timestamp_utc" not in df:
        raise ValueError("the file needs a timestamp column (timestamp / time / date)")
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True, errors="coerce")
    if "wind_speed_kmh" in df:                       # Open-Meteo wind is km/h
        df["wind_speed_ms"] = pd.to_numeric(df.pop("wind_speed_kmh"), errors="coerce") / 3.6
    for col in config.VARIABLES:
        df[col] = pd.to_numeric(df[col], errors="coerce") if col in df else float("nan")
    if "city" not in df:
        df["city"] = "unknown"
    df["source"] = df.get("source", "input_file")
    df["bronze_file"] = "input_file"
    df["priority"] = 1
    return df


def run_quality_checks(df_path: str) -> pd.DataFrame | None:
    """Check one hourly file with the Data Quality Agent and Quality Gate 2's
    record-level thresholds. Returns the cleaned data, or ``None`` if the file
    fails the gate (nothing trusted is replaced in that case)."""
    print(f"[Data Quality Agent] Inspecting dataset at: {df_path}")
    path = Path(df_path)
    if not path.exists():
        raise FileNotFoundError(f"Dataset not found at {df_path}. Run `make -C src data` to build data/silver first.")
    raw = pd.read_parquet(path) if path.suffix == ".parquet" else pd.read_csv(path)
    df = _standardise(raw)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    agent = DataQualityAgent(run_id)

    bad_ts = df["timestamp_utc"].isna()
    if bad_ts.any():
        agent._quarantine(raw[bad_ts.to_numpy()], "unparseable_timestamp", "timestamp could not be parsed")
        agent._log("unparseable_timestamp", "quarantine", "all", pd.Series(raw.index[bad_ts.to_numpy()]),
                   "timestamp could not be parsed")
        df = df[~bad_ts]

    cleaned = []
    for city, g in df.groupby("city"):
        g = agent.fix_units(g, city, "input_file")
        cleaned.append(agent.clean_city(g, None, city))
    out = pd.concat(cleaned, ignore_index=True) if cleaned else df.iloc[0:0]
    result = agent.result(out)

    n = max(1, len(out))
    valid = float((out["temperature_c"].notna() & out["humidity_pct"].notna()).mean()) if len(out) else 0.0
    q_rate = len(result.quarantine) / n
    last = out["timestamp_utc"].max() if len(out) else None
    lag_h = (datetime.now(timezone.utc) - last.to_pydatetime()).total_seconds() / 3600 if last is not None else None
    checks = [
        {"check": f"completeness >= {config.GATE2_MIN_COMPLETENESS:.0%}", "passed": valid >= config.GATE2_MIN_COMPLETENESS,
         "detail": f"{valid:.4f}"},
        {"check": f"quarantine rate <= {config.GATE2_MAX_QUARANTINE_RATE:.0%}", "passed": q_rate <= config.GATE2_MAX_QUARANTINE_RATE,
         "detail": f"{q_rate:.4f}"},
    ]
    passed = all(c["passed"] for c in checks)

    if len(result.quarantine):
        qdir = QUARANTINE_DIR / run_id
        qdir.mkdir(parents=True, exist_ok=True)
        result.quarantine.to_csv(qdir / "quarantined_records.csv", index=False)
        print(f"[Data Quality Agent] Quarantined {len(result.quarantine)} records to {qdir}")
    pipeline.append_jsonl(LOG_FILE, [dict(a, stage="member3_cli") for a in result.actions] + [{
        "run_id": run_id, "stage": "member3_cli", "rule": "quality_gate", "action": "pass" if passed else "fail",
        "reason": "; ".join(c["check"] for c in checks if not c["passed"]) or "all checks passed"}])
    _write_report({
        "run_id": run_id, "mode": "file", "source_file": str(df_path), "status": "PASSED" if passed else "FAILED",
        "total_records": len(raw), "hourly_records_after_cleaning": len(out), "quarantined_records": len(result.quarantine),
        "agent_actions": result.counts(), "checks": checks,
        "latest_timestamp_utc": pipeline.iso(last) if last is not None else None,
        "freshness_lag_hours": None if lag_h is None else round(lag_h, 1),
    })
    if not passed:
        print("[Quality Gate] FAILED - the file is not accepted; trusted data is unchanged.")
        return None
    print("[Quality Gate] PASSED")
    return out


def run_pipeline(update: bool = False) -> int:
    """Full automated run with both quality gates and last-trusted preservation."""
    rep = pipeline.run("update" if update else "data")
    status = pipeline.read_status()
    _write_report({
        "run_id": rep["run_id"], "mode": rep["mode"],
        "status": "PASSED" if rep["status"] == "success" else "FAILED",
        "error": rep.get("error"),
        "gate1_passed": rep.get("gate1", {}).get("passed"), "gate2_passed": rep.get("gate2", {}).get("passed"),
        "failed_checks": [c["check"] for g in ("gate1", "gate2") for c in rep.get(g, {}).get("checks", []) if not c["passed"]],
        "agent_actions": rep.get("agent_actions", {}),
        "freshness": status.get("freshness"),
        "serving_trusted_run": status.get("serving_run_id"),
        "full_report": f"reports/validation/validation_{rep['run_id']}.json",
    })
    if rep["status"] == "success":
        print(f"[Data Quality Agent] PASSED - Gold layer updated (run {rep['run_id']}).")
        return 0
    print(f"[Data Quality Agent] FAILED ({rep.get('error')}) - kept the last trusted Gold dataset "
          f"(run {status.get('serving_run_id')}).")
    return 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="HeatShield Data Quality Agent (Member 3)")
    ap.add_argument("--update", action="store_true", help="fetch the latest Open-Meteo data first (hourly refresh)")
    ap.add_argument("--file", help="check a single hourly CSV/parquet file instead of running the pipeline")
    args = ap.parse_args(argv)
    os.chdir(ROOT)
    if args.file:
        return 0 if run_quality_checks(args.file) is not None else 1
    return run_pipeline(update=args.update)


if __name__ == "__main__":
    sys.exit(main())
