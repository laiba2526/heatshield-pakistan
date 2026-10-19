import json
import time
import hashlib
from datetime import datetime, timezone
from pathlib import Path

import requests

CITIES = {
    "karachi":   (24.8607, 67.0011),
    "lahore":    (31.5497, 74.3436),
    "jacobabad": (28.2769, 68.4514),
}
YEARS = [2021, 2022, 2023, 2024, 2025]

POWER_DIR = Path("data/bronze/nasa_power")
DOCS_DIR = Path("data/bronze/documents")
URL_LIST = Path("docs/document_urls.txt")
MANIFEST = Path("data/manifest.json")

POWER_URL = "https://power.larc.nasa.gov/api/temporal/hourly/point"
HEADERS = {"User-Agent": "HeatShield-Pakistan-hackathon (student project)"}


def now():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def sha256_of(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def add_to_manifest(entry):
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    items = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else []
    items.append(entry)
    MANIFEST.write_text(json.dumps(items, indent=2))


def fetch_nasa_power():
    POWER_DIR.mkdir(parents=True, exist_ok=True)
    for city, (lat, lon) in CITIES.items():
        for year in YEARS:
            path = POWER_DIR / f"power_{city}_{year}.json"
            if path.exists():
                print("skip (already have)", path)
                continue
            params = {
                "parameters": "T2M,RH2M,T2MDEW,WS10M",
                "community": "RE",
                "latitude": lat,
                "longitude": lon,
                "start": f"{year}0101",
                "end": f"{year}1231",
                "format": "JSON",
                "time-standard": "UTC",
            }
            r = requests.get(POWER_URL, params=params, headers=HEADERS, timeout=300)
            r.raise_for_status()
            path.write_bytes(r.content)  # saved exactly as received
            add_to_manifest({
                "source": "NASA POWER",
                "publisher": "NASA Langley Research Center (POWER project)",
                "city": city,
                "year": year,
                "request_url": r.url,
                "licence": "FILL: wording from power.larc.nasa.gov",
                "downloaded_at_utc": now(),
                "file": str(path),
                "sha256": sha256_of(path),
            })
            print("saved", path)
            time.sleep(2)  # be polite to the server


def fetch_documents():
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    if not URL_LIST.exists():
        print("No docs/document_urls.txt found, skipping documents")
        return
    for line in URL_LIST.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "|" not in line:
            continue
        name, url = [x.strip() for x in line.split("|", 1)]
        if "PASTE-REAL" in url:
            print("skip placeholder:", name)
            continue
        path = DOCS_DIR / f"{name}.pdf"
        if path.exists():
            print("skip (already have)", path)
            continue
        r = requests.get(url, headers=HEADERS, timeout=120)
        r.raise_for_status()
        path.write_bytes(r.content)
        add_to_manifest({
            "source": "Official heatwave document",
            "publisher": "FILL: NDMA or PDMA Sindh",
            "title": name,
            "page_url": url,
            "licence": "FILL: wording from the site",
            "downloaded_at_utc": now(),
            "file": str(path),
            "sha256": sha256_of(path),
        })
        print("saved", path)
        time.sleep(2)


fetch_nasa_power()
fetch_documents()
print("Done. Manifest:", MANIFEST)