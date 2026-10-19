import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path

import requests

CITIES = {
    "karachi":   (24.8607, 67.0011),
    "lahore":    (31.5497, 74.3436),
    "jacobabad": (28.2769, 68.4514),
}
VARIABLES = "temperature_2m,relative_humidity_2m,dew_point_2m,wind_speed_10m"

BRONZE_DIR = Path("data/bronze/open_meteo")
MANIFEST = Path("data/manifest.json")

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"


def sha256_of(path):
    # A hash is a short code that changes if the file changes.
    return hashlib.sha256(path.read_bytes()).hexdigest()


def add_to_manifest(entry):
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    items = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else []
    items.append(entry)
    MANIFEST.write_text(json.dumps(items, indent=2))


def download(kind, city, url, params):
    response = requests.get(url, params=params, timeout=120)
    response.raise_for_status()

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    BRONZE_DIR.mkdir(parents=True, exist_ok=True)
    path = BRONZE_DIR / f"{kind}_{city}_{stamp}.json"
    path.write_bytes(response.content)  # saved exactly as received

    add_to_manifest({
        "source": "Open-Meteo",
        "publisher": "Open-Meteo.com",
        "kind": kind,
        "city": city,
        "request_url": response.url,
        "licence": "CC BY 4.0 (confirm on open-meteo.com)",
        "downloaded_at_utc": stamp,
        "file": str(path),
        "sha256": sha256_of(path),
    })
    print("saved", path)


for city, (lat, lon) in CITIES.items():
    base = {"latitude": lat, "longitude": lon,
            "hourly": VARIABLES, "timezone": "UTC"}

    # Forecast: next 3 days (covers the 24-48 hour goal)
    download("forecast", city, FORECAST_URL, {**base, "forecast_days": 3})

    # History: about 5 years (needed for the historical baseline)
    download("archive", city, ARCHIVE_URL,
             {**base, "start_date": "2021-10-01", "end_date": "2026-10-10"})