"""End-to-end pipeline: Bronze -> Gate 1 -> Data Quality Agent -> Silver ->
Gold -> predictions -> Gate 2 -> promote (or keep the last trusted data).

Outputs of a run are first written to ``data/_staging/<run_id>/``. Only when
Quality Gate 2 passes are they promoted to ``data/silver`` and ``data/gold``;
the previous trusted layers are moved to ``data/_archive`` for rollback.
When a gate fails nothing trusted is touched - the dashboard keeps serving
the last trusted dataset and shows the failure.

Usage::

    python -m heatshield.pipeline data       # full rebuild (= make -C src data)
    python -m heatshield.pipeline update     # hourly refresh: fetch + rebuild
    python -m heatshield.pipeline train      # retrain the prediction model
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
import traceback
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from heatshield import bronze, config
from heatshield.quality import DataQualityAgent
from heatshield.transform import add_hourly_heat_index, daily_heat_table
from heatshield.heat_index import risk_level

STATUS_FILE = config.STATUS / "run_status.json"
HISTORY_FILE = config.STATUS / "run_history.jsonl"
AUDIT_FILE = config.AUDIT / "audit_log.jsonl"
LOCK_FILE = config.STATUS / ".pipeline.lock"
PRIORITY_ARCHIVE = 9 * 10**13       # archive beats forecast-past rows for the same hour


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(ts) -> str | None:
    if ts is None or (isinstance(ts, float) and np.isnan(ts)) or pd.isna(ts):
        return None
    return pd.Timestamp(ts).tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ")


def _jsonable(obj):
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return None if np.isnan(obj) else float(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (pd.Timestamp, datetime)):
        return iso(obj)
    return obj


def append_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(_jsonable(rec), ensure_ascii=False) + "\n")


@contextmanager
def pipeline_lock(timeout_s: int = 900):
    """Only one pipeline run at a time (dashboard scheduler, cron and humans share data/)."""
    config.STATUS.mkdir(parents=True, exist_ok=True)
    start = time.time()
    while True:
        try:
            fd = os.open(LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            break
        except FileExistsError:
            if time.time() - LOCK_FILE.stat().st_mtime > timeout_s:   # stale lock from a crash
                LOCK_FILE.unlink(missing_ok=True)
                continue
            if time.time() - start > timeout_s:
                raise TimeoutError("another pipeline run holds the lock")
            time.sleep(2)
    try:
        yield
    finally:
        LOCK_FILE.unlink(missing_ok=True)


# ============================================================== silver build
def _forecast_rows(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split a forecast file into the hours before its issue time (recent past)
    and the hours after (the actual forecast)."""
    issued = pd.to_datetime(frame["issued_utc"].iloc[0], format="%Y%m%dT%H%M%SZ", utc=True)
    past = frame[frame["timestamp_utc"] < issued.floor("h")]
    future = frame[frame["timestamp_utc"] >= issued.floor("h")]
    return past, future


def build_silver(files: list[bronze.BronzeFile], agent: DataQualityAgent) -> dict:
    obs_parts, nasa_parts, era5_parts, latest_fc = {}, {}, {}, {}
    for bf in files:
        if bf.frame is None:
            continue
        df = agent.fix_units(bf.frame, bf.city, bf.source)
        if bf.source == "open_meteo_archive":
            df["priority"] = PRIORITY_ARCHIVE
            obs_parts.setdefault(bf.city, []).append(df)
        elif bf.source == "open_meteo_forecast":
            past, future = _forecast_rows(df)
            past = past.assign(priority=int(bf.stamp[:8] + bf.stamp[9:15]), source="open_meteo_recent")
            obs_parts.setdefault(bf.city, []).append(past)
            if bf.stamp >= latest_fc.get(bf.city, ("",))[0]:
                latest_fc[bf.city] = (bf.stamp, future)
        elif bf.source == "nasa_power":
            nasa_parts.setdefault(bf.city, []).append(df)
        elif bf.source == "era5":
            era5_parts.setdefault(bf.city, []).append(df)

    obs, nasa, era5, forecast, cross = [], [], [], [], []
    for city in config.CITIES:
        n = pd.concat(nasa_parts.get(city, []), ignore_index=True) if city in nasa_parts else None
        if n is not None:
            n = n.sort_values("timestamp_utc").drop_duplicates("timestamp_utc", keep="last")
            nasa.append(n)
        if city in era5_parts:
            era5.append(pd.concat(era5_parts[city], ignore_index=True).drop_duplicates("timestamp_utc"))
        if city in obs_parts:
            cleaned = agent.clean_city(pd.concat(obs_parts[city], ignore_index=True), n, city)
            obs.append(cleaned)
            cross.append(agent.cross_check(cleaned, n, city))
        if city in latest_fc:
            fc = latest_fc[city][1].assign(priority=0)
            fc_clean = agent.clean_city(fc, None, f"{city}/forecast")
            fc_clean["city"] = city
            fc_clean["issued_utc"] = latest_fc[city][0]
            forecast.append(fc_clean)

    cols = ["city", "timestamp_utc", *config.VARIABLES, "source", "qc_flag", "qc_notes"]
    def cat(parts, keep):
        if not parts:
            return pd.DataFrame(columns=keep)
        df = pd.concat(parts, ignore_index=True)
        return df[[c for c in keep if c in df.columns]].reset_index(drop=True)
    ref_cols = ["city", "timestamp_utc", *config.VARIABLES, "source"]
    return {
        "weather_hourly": cat(obs, cols),
        "forecast_hourly": cat(forecast, cols + ["issued_utc"]),
        "nasa_power_hourly": cat(nasa, ref_cols),
        "era5_hourly": cat(era5, ref_cols),
        "cross_source_daily": cat(cross, ["city", "date", "tmax_primary", "tmax_nasa", "diff"]),
    }


def source_agreement(silver: dict) -> pd.DataFrame:
    """Daily Tmax agreement of the primary series with each reference source."""
    def dmax(df):
        if df.empty:
            return pd.Series(dtype=float)
        d = df.assign(date=df["timestamp_utc"].dt.tz_convert(config.LOCAL_TZ).dt.normalize().dt.tz_localize(None))
        return d.groupby(["city", "date"])["temperature_c"].max()
    primary = dmax(silver["weather_hourly"])
    rows = []
    for name in ("nasa_power_hourly", "era5_hourly"):
        ref = dmax(silver[name])
        both = pd.concat({"p": primary, "r": ref}, axis=1).dropna()
        for city, g in both.groupby(level="city"):
            diff = g["p"] - g["r"]
            rows.append({"reference": name.replace("_hourly", ""), "city": city, "days": len(g),
                         "tmax_bias_c": round(float(diff.mean()), 2), "tmax_mae_c": round(float(diff.abs().mean()), 2),
                         "tmax_corr": round(float(g["p"].corr(g["r"])), 3)})
    return pd.DataFrame(rows)


# ================================================================ gold build
def build_gold(silver: dict, model) -> dict:
    daily = daily_heat_table(silver["weather_hourly"])
    fc_hourly = add_hourly_heat_index(silver["forecast_hourly"]) if len(silver["forecast_hourly"]) else pd.DataFrame()
    if len(fc_hourly):
        fc_hourly["local_time"] = fc_hourly["local_time"].astype(str)
        # The forecast starts at its issue hour, so "today" would be incomplete:
        # complete today's earlier hours with the observed series.
        fc = silver["forecast_hourly"].drop(columns=["issued_utc"])
        obs = silver["weather_hourly"]
        parts = [fc]
        for city, g in fc.groupby("city"):
            first = g["timestamp_utc"].min()
            day_start = first.tz_convert(config.LOCAL_TZ).normalize().tz_convert("UTC")
            o = obs[(obs["city"] == city) & (obs["timestamp_utc"] >= day_start) & (obs["timestamp_utc"] < first)]
            parts.append(o)
        fc_daily = daily_heat_table(pd.concat(parts, ignore_index=True), id_prefix="nwp-")
        issued = silver["forecast_hourly"].groupby("city")["issued_utc"].max()
        fc_daily["issued_utc"] = fc_daily["city"].map(issued)
        fc_daily["row_id"] = fc_daily["row_id"] + "-" + fc_daily["issued_utc"].astype(str)
    else:
        fc_daily = pd.DataFrame()

    preds = pd.DataFrame()
    if model is not None:
        p = model.forecast_from(daily)
        if len(p):
            p["predicted_risk_level"] = risk_level(p["pred"].to_numpy())
            p["upper90_risk_level"] = risk_level(p["hi90"].to_numpy())
            p["row_id"] = "pred-" + p["city"] + "-" + p["target_date"].dt.strftime("%Y%m%d") + "-h" + p["horizon"].astype(str)
            p["issued_from_row_id"] = p["city"] + "-" + p["issue_date"].dt.strftime("%Y%m%d")
            keep = ["row_id", "city", "issue_date", "target_date", "horizon", "pred", "lo80", "hi80", "lo90", "hi90",
                    "predicted_risk_level", "upper90_risk_level", "clim_target", "issued_from_row_id"]
            preds = p[keep].round({c: 2 for c in ("pred", "lo80", "hi80", "lo90", "hi90", "clim_target")})
    return {"heat_daily": daily, "forecast_hourly": fc_hourly, "forecast_daily": fc_daily, "predictions": preds}


# ================================================================== gates
def gate1_summary(files: list[bronze.BronzeFile]) -> dict:
    checks = []
    results = [f.summary() for f in files]
    for city in config.CITIES:
        have_archive = any(f.passed and f.city == city and f.source == "open_meteo_archive" for f in files)
        checks.append({"check": f"{city}: trusted archive file available", "passed": have_archive, "severity": "error"})
        have_fc = any(f.passed and f.city == city and f.source == "open_meteo_forecast" for f in files)
        checks.append({"check": f"{city}: forecast file available", "passed": have_fc, "severity": "error"})
    rejected = [r["file"] for r in results if not r["passed"]]
    checks.append({"check": "no Bronze file rejected", "passed": not rejected, "severity": "warning",
                   "detail": f"rejected={rejected}"})
    return {"gate": "gate1_bronze_files", "passed": all(c["passed"] for c in checks if c["severity"] == "error"),
            "checks": checks, "files": results}


def gate2(silver: dict, gold: dict, agent_counts: dict, quarantine: pd.DataFrame, trusted: dict | None) -> dict:
    checks = []
    def add(name, ok, detail="", severity="error"):
        checks.append({"check": name, "passed": bool(ok), "detail": detail, "severity": severity})

    hourly, daily = silver["weather_hourly"], gold["heat_daily"]
    for city in config.CITIES:
        h = hourly[hourly["city"] == city]
        n = len(h)
        valid = int((h["temperature_c"].notna() & h["humidity_pct"].notna()).sum())
        compl = valid / n if n else 0.0
        add(f"{city}: hourly completeness >= {config.GATE2_MIN_COMPLETENESS:.0%}", compl >= config.GATE2_MIN_COMPLETENESS,
            f"{compl:.4f} ({valid}/{n})")
        q = int((quarantine["city"] == city).sum()) if len(quarantine) and "city" in quarantine else 0
        rate = q / n if n else 1.0
        add(f"{city}: quarantine rate <= {config.GATE2_MAX_QUARANTINE_RATE:.0%}", rate <= config.GATE2_MAX_QUARANTINE_RATE,
            f"{rate:.4f} ({q} records)")
        days = int(daily.loc[daily["city"] == city, "complete_day"].sum())
        add(f"{city}: >= {config.GATE2_MIN_DAYS_PER_CITY} complete days", days >= config.GATE2_MIN_DAYS_PER_CITY, f"{days}")
        if trusted and city in trusted.get("last_observation_utc", {}):
            new_last = iso(h["timestamp_utc"].max()) if n else None
            old_last = trusted["last_observation_utc"][city]
            add(f"{city}: no time regression vs trusted data", new_last is not None and (old_last is None or new_last >= old_last),
                f"new={new_last} trusted={old_last}")
        fc = gold["forecast_hourly"]
        fc_h = int((fc["city"] == city).sum()) if len(fc) else 0
        add(f"{city}: forecast covers >= 48 h", fc_h >= 48, f"{fc_h} hours")

    add("gold row_id unique", daily["row_id"].is_unique, f"{len(daily)} rows")
    hi = daily.loc[daily["complete_day"], "hi_max_c"]
    add("gold heat index finite on complete days", hi.notna().all(), f"nan={int(hi.isna().sum())}")
    add("gold heat index within [-30, 80] C", hi.between(-30, 80).all(), f"min={hi.min():.1f} max={hi.max():.1f}")
    add("gold risk levels valid", daily.loc[daily["complete_day"], "risk_level"].ne("Unknown").all())
    if trusted and trusted.get("gold_rows"):
        add("no silent loss of gold rows", len(daily) >= 0.98 * trusted["gold_rows"],
            f"new={len(daily)} trusted={trusted['gold_rows']}")
    p = gold["predictions"]
    if len(p):
        add("predictions finite", np.isfinite(p[["pred", "lo90", "hi90"]].to_numpy()).all(), f"{len(p)} rows")
        add("prediction intervals ordered", (p["lo90"] <= p["pred"]).all() and (p["pred"] <= p["hi90"]).all())
    else:
        add("model predictions produced", False, "no trained model found - run `make -C src train`", severity="warning")
    return {"gate": "gate2_publish", "passed": all(c["passed"] for c in checks if c["severity"] == "error"),
            "checks": checks}


# =========================================================== write/promote
def write_layers(root: Path, silver: dict, gold: dict, extras: dict) -> None:
    (root / "silver").mkdir(parents=True, exist_ok=True)
    (root / "gold").mkdir(parents=True, exist_ok=True)
    for name, df in silver.items():
        df.to_parquet(root / "silver" / f"{name}.parquet", index=False)
    gold["heat_daily"].assign(date=gold["heat_daily"]["date"].dt.strftime("%Y-%m-%d")).to_csv(
        root / "gold" / "heat_daily.csv", index=False)
    for name in ("forecast_daily", "predictions"):
        df = gold[name].copy()
        for c in df.columns:
            if pd.api.types.is_datetime64_any_dtype(df[c]):
                df[c] = df[c].dt.strftime("%Y-%m-%d")
        df.to_csv(root / "gold" / f"{name}.csv", index=False)
    if len(gold["forecast_hourly"]):
        gold["forecast_hourly"].drop(columns=["date"]).to_parquet(root / "gold" / "forecast_hourly.parquet", index=False)
    for name, df in extras.items():
        df.to_csv(root / "gold" / f"{name}.csv", index=False)


def promote(stage: Path, run_id: str, keep: int = 3) -> None:
    config.ARCHIVE.mkdir(parents=True, exist_ok=True)
    for layer in ("silver", "gold"):
        live = config.DATA / layer
        if live.exists():
            shutil.move(str(live), str(config.ARCHIVE / f"{layer}_before_{run_id}"))
        shutil.move(str(stage / layer), str(live))
    for layer in ("silver", "gold"):
        old = sorted(config.ARCHIVE.glob(f"{layer}_before_*"))
        for path in old[:-keep]:
            shutil.rmtree(path, ignore_errors=True)
    shutil.rmtree(stage, ignore_errors=True)


def read_status() -> dict:
    try:
        return json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def freshness(silver: dict, now: datetime) -> dict:
    out = {}
    for city in config.CITIES:
        h = silver["weather_hourly"]
        last = h.loc[(h["city"] == city) & h["temperature_c"].notna(), "timestamp_utc"].max()
        fc = silver["forecast_hourly"]
        issued = fc.loc[fc["city"] == city, "issued_utc"].max() if len(fc) else None
        issued_ts = pd.to_datetime(issued, format="%Y%m%dT%H%M%SZ", utc=True) if isinstance(issued, str) else None
        obs_age = (now - last.to_pydatetime()).total_seconds() / 3600 if pd.notna(last) else None
        fc_age = (now - issued_ts.to_pydatetime()).total_seconds() / 3600 if issued_ts is not None else None
        out[city] = {
            "last_observation_utc": iso(last), "observation_age_hours": None if obs_age is None else round(obs_age, 1),
            "forecast_issued_utc": iso(issued_ts), "forecast_age_hours": None if fc_age is None else round(fc_age, 1),
            "observations_stale": obs_age is None or obs_age > config.FRESHNESS_STALE_HOURS,
            "forecast_stale": fc_age is None or fc_age > config.FRESHNESS_FORECAST_STALE_HOURS,
        }
    return out


# ===================================================================== run
def run(mode: str = "data", fetch: bool | None = None, mutate=None, note: str | None = None) -> dict:
    """Run the pipeline. ``mutate`` (tests / fault drills) may corrupt the
    Bronze frames after Gate 1 to prove that bad data cannot replace trusted data.
    ``note`` labels the run in the run history and audit log (e.g. a fault drill)."""
    from heatshield.model import HeatShieldModel   # local import keeps the module light

    started = utcnow()
    run_id = started.strftime("%Y%m%dT%H%M%SZ")
    status_before = read_status()
    report: dict = {"run_id": run_id, "mode": mode, "started_utc": iso(started), "note": note}
    agent = DataQualityAgent(run_id)
    stage = config.STAGING / run_id

    with pipeline_lock():
        try:
            if fetch if fetch is not None else mode == "update":
                from heatshield.fetch import fetch_forecasts
                report["fetch"] = fetch_forecasts()

            manifest = bronze.load_manifest()
            files = [bronze.read_and_gate(bf, manifest) for bf in bronze.discover()]
            report["gate1"] = gate1_summary(files)
            if mutate is not None:
                mutate(files)
            if not report["gate1"]["passed"]:
                raise GateFailure("Quality Gate 1 failed")

            silver = build_silver(files, agent)
            model = HeatShieldModel.load()
            if model is None or mode == "train":
                daily_for_training = daily_heat_table(silver["weather_hourly"])
                model = HeatShieldModel.train(daily_for_training)
                model.save()
                report["model_trained"] = True
            gold = build_gold(silver, model)
            agreement = source_agreement(silver)
            result = agent.result(silver["weather_hourly"])
            report["agent_actions"] = result.counts()
            trusted = status_before.get("trusted_snapshot")
            report["gate2"] = gate2(silver, gold, result.counts(), result.quarantine, trusted)

            write_layers(stage, silver, gold, {"source_agreement": agreement})
            if not report["gate2"]["passed"]:
                raise GateFailure("Quality Gate 2 failed")
            promote(stage, run_id)
            status = "success"
            report["freshness"] = freshness(silver, utcnow())
            report["trusted_snapshot"] = {
                "run_id": run_id,
                "gold_rows": int(len(gold["heat_daily"])),
                "last_observation_utc": {c: v["last_observation_utc"] for c, v in report["freshness"].items()},
            }
        except GateFailure as exc:
            status, report["error"] = "failed_validation", str(exc)
        except Exception as exc:   # noqa: BLE001 - any crash must still be recorded
            status, report["error"] = "error", f"{type(exc).__name__}: {exc}"
            report["traceback"] = traceback.format_exc()[-4000:]
        # A failed run leaves its candidate outputs in data/_staging/<run_id>
        # for inspection; only the newest few are kept.
        for old in sorted(config.STAGING.glob("*"))[:-3] if config.STAGING.exists() else []:
            shutil.rmtree(old, ignore_errors=True)

        # --- quarantine, audit, reports and status are written for every run
        result = agent.result(pd.DataFrame())
        if len(result.quarantine):
            qdir = config.QUARANTINE / run_id
            qdir.mkdir(parents=True, exist_ok=True)
            result.quarantine.to_csv(qdir / "quarantined_records.csv", index=False)
        finished = utcnow()
        report.update({"status": status, "finished_utc": iso(finished),
                       "duration_s": round((finished - started).total_seconds(), 1)})
        audit = [{"run_id": run_id, "ts_utc": iso(finished), "stage": "pipeline", "rule": "run",
                  "action": status, "reason": report.get("error", "all gates passed"), "note": note}]
        for gate in ("gate1", "gate2"):
            if gate in report:
                audit.append({"run_id": run_id, "ts_utc": iso(finished), "stage": gate, "rule": "quality_gate",
                              "action": "pass" if report[gate]["passed"] else "fail",
                              "reason": "; ".join(c["check"] for c in report[gate]["checks"] if not c["passed"]) or "all checks passed"})
        audit += [dict(a, ts_utc=iso(finished)) for a in result.actions]
        append_jsonl(AUDIT_FILE, audit)

        config.REPORTS.mkdir(parents=True, exist_ok=True)
        (config.REPORTS / "validation").mkdir(exist_ok=True)
        (config.REPORTS / "validation" / f"validation_{run_id}.json").write_text(
            json.dumps(_jsonable(report), indent=2), encoding="utf-8")
        _prune(config.REPORTS / "validation", "validation_*.json", 200)

        new_status = dict(status_before)
        new_status.update({"last_run_id": run_id, "last_run_utc": iso(finished), "last_run_status": status,
                           "last_run_error": report.get("error"), "last_run_mode": mode,
                           "gate1_passed": report.get("gate1", {}).get("passed"),
                           "gate2_passed": report.get("gate2", {}).get("passed")})
        if "fetch" in report:
            new_status["last_fetch"] = {"utc": iso(finished), **report["fetch"]}
        if status == "success":
            new_status.update({"last_success_run_id": run_id, "last_success_utc": iso(finished),
                               "freshness": report["freshness"], "trusted_snapshot": report["trusted_snapshot"]})
        new_status["serving_run_id"] = new_status.get("last_success_run_id")
        config.STATUS.mkdir(parents=True, exist_ok=True)
        STATUS_FILE.write_text(json.dumps(_jsonable(new_status), indent=2), encoding="utf-8")
        append_jsonl(HISTORY_FILE, [{"run_id": run_id, "mode": mode, "status": status, "finished_utc": iso(finished),
                                     "duration_s": report["duration_s"], "error": report.get("error"),
                                     "gate1": report.get("gate1", {}).get("passed"),
                                     "gate2": report.get("gate2", {}).get("passed"),
                                     "agent_actions": report.get("agent_actions", {}), "note": note}])
    return report


class GateFailure(RuntimeError):
    pass


def _prune(folder: Path, pattern: str, keep: int) -> None:
    files = sorted(folder.glob(pattern))
    for f in files[:-keep]:
        f.unlink(missing_ok=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=["data", "update", "train"])
    ap.add_argument("--no-fetch", action="store_true", help="update mode without network access")
    args = ap.parse_args(argv)
    rep = run(args.mode, fetch=False if args.no_fetch else None)
    print(f"[{rep['run_id']}] {args.mode}: {rep['status']} in {rep['duration_s']}s")
    for gate in ("gate1", "gate2"):
        if gate in rep:
            failed = [c for c in rep[gate]["checks"] if not c["passed"]]
            print(f"  {gate}: {'PASS' if rep[gate]['passed'] else 'FAIL'}"
                  + "".join(f"\n    - [{c['severity']}] {c['check']} {c.get('detail', '')}" for c in failed))
    if rep.get("agent_actions"):
        print("  data quality agent:", rep["agent_actions"])
    if rep.get("fetch"):
        print("  fetch:", len(rep["fetch"]["fetched"]), "files,", len(rep["fetch"]["failed"]), "failures")
    if rep.get("error"):
        print("  error:", rep["error"])
    return 0 if rep["status"] == "success" else 1


if __name__ == "__main__":
    sys.exit(main())
