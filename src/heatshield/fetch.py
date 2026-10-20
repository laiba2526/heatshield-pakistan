"""Downloads into the Bronze layer (raw bytes saved exactly as received).

* ``fetch_forecasts`` - the hourly refresh: Open-Meteo forecast API (4 days, so
  the third local Pakistan day is complete despite the UTC+5 offset) with
  ``past_days`` so the most recent observed-period hours (which the archive
  API only publishes with a delay of several days) are refreshed too.
* ``fetch_era5`` - Copernicus ERA5 reanalysis for the three cities, served
  through Open-Meteo's historical API with ``models=era5`` (no CDS account
  needed; ``make -C src era5``). docs/DEPLOYMENT.md describes the official CDS route.

Every saved file gets a manifest entry with URL, licence, UTC download time
and SHA-256, in the same format Member 1 used.
"""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from heatshield import config

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
VARIABLES = "temperature_2m,relative_humidity_2m,dew_point_2m,wind_speed_10m"
HEADERS = {"User-Agent": "HeatShield-Pakistan (student project; hourly refresh)"}
OPEN_METEO_LICENCE = ("CC BY 4.0 - Open-Meteo.com (https://open-meteo.com/en/license); "
                      "free API for non-commercial use per https://open-meteo.com/en/terms")
ERA5_LICENCE = ("CC BY 4.0 (C3S, since 2 Jul 2025; https://cds.climate.copernicus.eu/licences/cc-by). "
                "delivered via Open-Meteo (CC BY 4.0). Attribution: Hersbach et al. (2023) ERA5 hourly data "
                "on single levels, C3S CDS, DOI 10.24381/cds.adbb2d47")
ERA5_DIR = config.BRONZE / "era5"


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def add_to_manifest(entry: dict) -> None:
    items = json.loads(config.MANIFEST.read_text(encoding="utf-8")) if config.MANIFEST.exists() else []
    items.append(entry)
    tmp = config.MANIFEST.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(items, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(config.MANIFEST)


def _save(response: requests.Response, path: Path, entry: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(response.content)
    entry.update({
        "request_url": response.url,
        "downloaded_at_utc": path.stem.rsplit("_", 1)[-1] if path.stem[-1] == "Z" else _stamp(),
        "file": path.relative_to(config.ROOT).as_posix(),
        "sha256": hashlib.sha256(response.content).hexdigest(),
    })
    add_to_manifest(entry)
    return path


def fetch_forecasts(past_days: int = 14, forecast_days: int = 4, timeout: int = 60) -> dict:
    """Fetch the latest forecast for each city. Never raises: failures are reported."""
    result = {"fetched": [], "failed": []}
    for city, c in config.CITIES.items():
        params = {"latitude": c["lat"], "longitude": c["lon"], "hourly": VARIABLES, "timezone": "UTC",
                  "past_days": past_days, "forecast_days": forecast_days}
        try:
            r = requests.get(FORECAST_URL, params=params, headers=HEADERS, timeout=timeout)
            r.raise_for_status()
            json.loads(r.content)            # do not store a body that is not JSON
            path = config.BRONZE_OPEN_METEO / f"forecast_{city}_{_stamp()}.json"
            _save(r, path, {"source": "Open-Meteo", "publisher": "Open-Meteo.com", "kind": "forecast",
                            "city": city, "licence": OPEN_METEO_LICENCE})
            result["fetched"].append(path.name)
        except (requests.RequestException, ValueError) as exc:
            result["failed"].append({"city": city, "error": f"{type(exc).__name__}: {str(exc)[:200]}"})
    return result


def fetch_era5(start: str = "2021-10-01", end: str = "2026-10-10", timeout: int = 300) -> list[Path]:
    saved = []
    for city, c in config.CITIES.items():
        params = {"latitude": c["lat"], "longitude": c["lon"], "hourly": VARIABLES, "timezone": "UTC",
                  "models": "era5", "start_date": start, "end_date": end}
        r = requests.get(ARCHIVE_URL, params=params, headers=HEADERS, timeout=timeout)
        r.raise_for_status()
        json.loads(r.content)
        path = ERA5_DIR / f"era5_{city}_{_stamp()}.json"
        saved.append(_save(r, path, {
            "source": "Copernicus ERA5",
            "publisher": "ECMWF - Copernicus Climate Change Service (C3S); delivered by Open-Meteo.com",
            "kind": "reanalysis", "city": city, "period": f"{start}/{end}", "licence": ERA5_LICENCE,
            "notes": "Open-Meteo resamples ERA5 (0.25 deg) to the requested point; values are gridded "
                     "reanalysis, not station observations.",
        }))
        time.sleep(1)
    return saved


if __name__ == "__main__":
    for p in fetch_era5():
        print("saved", p.relative_to(config.ROOT).as_posix())
