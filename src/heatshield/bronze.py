"""Readers for the raw Bronze files plus Quality Gate 1 (file-level checks).

Gate 1 runs on every Bronze file *before* any record is used:
  * the file is listed in data/manifest.json and its SHA-256 still matches
    (provenance: raw data must never be silently edited),
  * the JSON parses and carries the variables we expect,
  * the declared units are the ones we know how to convert,
  * timestamps parse and are hourly.
A file that fails Gate 1 is rejected as a whole and never reaches Silver.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from heatshield import config

OPEN_METEO_VARS = {
    "temperature_2m": "temperature_c",
    "relative_humidity_2m": "humidity_pct",
    "dew_point_2m": "dew_point_c",
    "wind_speed_10m": "wind_speed_raw",
}
NASA_VARS = {
    "T2M": "temperature_c",
    "RH2M": "humidity_pct",
    "T2MDEW": "dew_point_c",
    "WS10M": "wind_speed_raw",
}
# Known unit spellings -> factor that converts the wind speed to m/s.
WIND_TO_MS = {"km/h": 1 / 3.6, "kmh": 1 / 3.6, "m/s": 1.0, "ms": 1.0, "mph": 0.44704, "kn": 0.514444}
TEMP_UNITS = {"°c", "c", "degc"}
NASA_FILL_VALUE = -999.0

_FILE_RE = re.compile(r"^(?P<kind>archive|forecast)_(?P<city>[a-z]+)_(?P<stamp>\d{8}T\d{6}Z)\.json$")
_NASA_RE = re.compile(r"^power_(?P<city>[a-z]+)_(?P<year>\d{4})\.json$")
_ERA5_RE = re.compile(r"^era5_(?P<city>[a-z]+)_(?P<stamp>\d{8}T\d{6}Z)\.json$")


@dataclass
class BronzeFile:
    path: Path
    source: str              # open_meteo_archive | open_meteo_forecast | nasa_power
    city: str
    stamp: str = ""          # download time for Open-Meteo files
    passed: bool = True
    checks: list = field(default_factory=list)
    frame: pd.DataFrame | None = None

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        self.checks.append({"check": name, "passed": bool(ok), "detail": detail})
        if not ok:
            self.passed = False
        return ok

    def summary(self) -> dict:
        return {
            "file": self.path.relative_to(config.ROOT).as_posix(),
            "source": self.source,
            "city": self.city,
            "passed": self.passed,
            "rows": 0 if self.frame is None else int(len(self.frame)),
            "checks": self.checks,
        }


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_manifest() -> dict[str, dict]:
    """Manifest entries keyed by posix path relative to the repo root."""
    if not config.MANIFEST.exists():
        return {}
    items = json.loads(config.MANIFEST.read_text(encoding="utf-8"))
    return {str(item["file"]).replace("\\", "/"): item for item in items}


def discover(max_forecasts_per_city: int = 72) -> list[BronzeFile]:
    """Find the Bronze files a pipeline run should use.

    * the newest Open-Meteo archive per city (archives overlap completely),
    * the newest ``max_forecasts_per_city`` forecast files per city (their
      ``past_days`` part supplies the most recent hours the archive lacks),
    * the newest ERA5 file per city (independent-reanalysis cross-check),
    * every NASA POWER city-year file (cross-check and gap-fill source).
    """
    files: list[BronzeFile] = []
    by_city: dict[tuple[str, str], list[tuple[str, Path]]] = {}
    for path in sorted(config.BRONZE_OPEN_METEO.glob("*.json")):
        m = _FILE_RE.match(path.name)
        if m and m["city"] in config.CITIES:
            by_city.setdefault((m["kind"], m["city"]), []).append((m["stamp"], path))
    for (kind, city), items in sorted(by_city.items()):
        items.sort()
        keep = items[-1:] if kind == "archive" else items[-max_forecasts_per_city:]
        for stamp, path in keep:
            files.append(BronzeFile(path, f"open_meteo_{kind}", city, stamp))
    era5: dict[str, tuple[str, Path]] = {}
    for path in sorted((config.BRONZE / "era5").glob("*.json")):
        m = _ERA5_RE.match(path.name)
        if m and m["city"] in config.CITIES:
            era5[m["city"]] = max(era5.get(m["city"], ("", path)), (m["stamp"], path))
    for city, (stamp, path) in sorted(era5.items()):
        files.append(BronzeFile(path, "era5", city, stamp))
    for path in sorted(config.BRONZE_NASA.glob("*.json")):
        m = _NASA_RE.match(path.name)
        if m and m["city"] in config.CITIES:
            files.append(BronzeFile(path, "nasa_power", m["city"], m["year"]))
    return files


def _verify_provenance(bf: BronzeFile, manifest: dict[str, dict]) -> None:
    rel = bf.path.relative_to(config.ROOT).as_posix()
    entry = manifest.get(rel)
    if not bf.check("listed_in_manifest", entry is not None, rel):
        return
    actual = sha256_of(bf.path)
    bf.check("sha256_matches_manifest", actual == entry.get("sha256"),
             f"manifest={str(entry.get('sha256'))[:12]} actual={actual[:12]}")


def _parse_open_meteo(bf: BronzeFile, raw: dict) -> None:
    hourly, units = raw.get("hourly"), raw.get("hourly_units", {})
    if not bf.check("has_hourly_block", isinstance(hourly, dict) and "time" in hourly):
        return
    missing = [v for v in OPEN_METEO_VARS if v not in hourly]
    if not bf.check("expected_variables_present", not missing, f"missing={missing}"):
        return
    t_unit = str(units.get("temperature_2m", "")).lower()
    w_unit = str(units.get("wind_speed_10m", "")).lower()
    bf.check("temperature_unit_known", t_unit in TEMP_UNITS, t_unit)
    if not bf.check("wind_unit_known", w_unit in WIND_TO_MS, w_unit):
        return
    df = pd.DataFrame({new: hourly[old] for old, new in OPEN_METEO_VARS.items()})
    df["timestamp_utc"] = pd.to_datetime(pd.Series(hourly["time"]), utc=True, errors="coerce")
    df["wind_speed_ms"] = pd.to_numeric(df.pop("wind_speed_raw"), errors="coerce") * WIND_TO_MS[w_unit]
    df["wind_unit_raw"] = w_unit
    bf.frame = df


def _parse_nasa(bf: BronzeFile, raw: dict) -> None:
    params = raw.get("properties", {}).get("parameter")
    if not bf.check("has_parameter_block", isinstance(params, dict)):
        return
    missing = [v for v in NASA_VARS if v not in params]
    if not bf.check("expected_variables_present", not missing, f"missing={missing}"):
        return
    units = {k: str(v.get("units", "")).lower() for k, v in raw.get("parameters", {}).items()}
    bf.check("temperature_unit_known", units.get("T2M", "c") in TEMP_UNITS, units.get("T2M", ""))
    w_unit = units.get("WS10M", "m/s")
    if not bf.check("wind_unit_known", w_unit in WIND_TO_MS, w_unit):
        return
    df = pd.DataFrame({new: pd.Series(params[old]) for old, new in NASA_VARS.items()})
    df = df.replace(NASA_FILL_VALUE, float("nan"))   # NASA POWER fill value -> missing
    stamps = pd.Series(df.index.astype(str))
    df = df.reset_index(drop=True)
    df["timestamp_utc"] = pd.to_datetime(stamps, format="%Y%m%d%H", utc=True, errors="coerce")
    df["wind_speed_ms"] = pd.to_numeric(df.pop("wind_speed_raw"), errors="coerce") * WIND_TO_MS[w_unit]
    df["wind_unit_raw"] = w_unit
    bf.frame = df


def read_and_gate(bf: BronzeFile, manifest: dict[str, dict]) -> BronzeFile:
    """Quality Gate 1 for one file. Leaves ``bf.frame`` set only if every check passed."""
    _verify_provenance(bf, manifest)
    try:
        raw = json.loads(bf.path.read_text(encoding="utf-8"))
        bf.check("json_parses", True)
    except (OSError, ValueError) as exc:
        bf.check("json_parses", False, str(exc)[:200])
        return bf
    if bf.source == "nasa_power":
        _parse_nasa(bf, raw)
    else:
        _parse_open_meteo(bf, raw)
    if bf.frame is not None:
        df = bf.frame
        bad_ts = int(df["timestamp_utc"].isna().sum())
        bf.check("timestamps_parse", bad_ts == 0, f"unparseable={bad_ts}")
        steps = df["timestamp_utc"].dropna().sort_values().diff().dropna()
        hourly_share = float((steps == pd.Timedelta(hours=1)).mean()) if len(steps) else 0.0
        bf.check("hourly_cadence", hourly_share >= 0.99, f"share_of_1h_steps={hourly_share:.4f}")
        bf.check("non_empty", len(df) > 0, f"rows={len(df)}")
        df["city"] = bf.city
        df["source"] = bf.source
        df["issued_utc"] = bf.stamp if bf.source.startswith("open_meteo") else ""
        df["bronze_file"] = bf.path.name
    if not bf.passed:
        bf.frame = None
    return bf
