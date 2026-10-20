"""Central configuration: paths, cities, physical limits, risk thresholds.

Everything that more than one module needs lives here so the pipeline, the
Data Quality Agent, the model and the dashboard always agree on the same numbers.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"

BRONZE = DATA / "bronze"
BRONZE_OPEN_METEO = BRONZE / "open_meteo"
BRONZE_NASA = BRONZE / "nasa_power"
BRONZE_DOCS = BRONZE / "documents"
MANIFEST = DATA / "manifest.json"

SILVER = DATA / "silver"
GOLD = DATA / "gold"                 # always the LAST TRUSTED gold layer
STAGING = DATA / "_staging"          # candidate outputs of the current run
ARCHIVE = DATA / "_archive"          # previous trusted gold layers (rollback)
QUARANTINE = DATA / "quarantine"
AUDIT = DATA / "audit"
STATUS = DATA / "status"

MODELS = ROOT / "models"
REPORTS = ROOT / "reports"
DOCS = ROOT / "docs"

LOCAL_TZ = "Asia/Karachi"            # PKT, UTC+5, no DST

CITIES = {
    "karachi":   {"name": "Karachi",   "lat": 24.8607, "lon": 67.0011},
    "lahore":    {"name": "Lahore",    "lat": 31.5497, "lon": 74.3436},
    "jacobabad": {"name": "Jacobabad", "lat": 28.2769, "lon": 68.4514},
}

# Canonical silver schema (units in the column names on purpose).
VARIABLES = ["temperature_c", "humidity_pct", "dew_point_c", "wind_speed_ms"]

# Physical plausibility limits used by the Data Quality Agent.
LIMITS = {
    "temperature_c": (-30.0, 60.0),
    "humidity_pct": (0.0, 100.0),
    "dew_point_c": (-50.0, 40.0),
    "wind_speed_ms": (0.0, 75.0),
}
MAX_TEMP_STEP_C_PER_HOUR = 10.0      # larger hourly jumps are treated as spikes
STUCK_HOURS = 12                     # identical values for this long = stuck feed
INTERPOLATE_MAX_GAP_H = 3            # short gaps are interpolated
NASA_FILL_MAX_GAP_H = 24             # medium gaps are filled from NASA POWER
CROSS_SOURCE_TMAX_TOL_C = 6.0        # daily Tmax disagreement that gets flagged

# Quality gate 2 thresholds (dataset level).
GATE2_MIN_COMPLETENESS = 0.95        # share of valid hourly records per city
GATE2_MAX_QUARANTINE_RATE = 0.02     # share of records quarantined per city
GATE2_MIN_DAYS_PER_CITY = 365
FRESHNESS_STALE_HOURS = 6            # observations older than this are "stale"
FRESHNESS_FORECAST_STALE_HOURS = 3   # hourly refresh should keep this fresh

# NWS heat-index risk categories, converted to deg C.
# (80 F, 90 F, 103 F, 125 F) -> (26.7, 32.2, 39.4, 51.7) deg C
RISK_LEVELS = [
    ("Low", -999.0, "#4c9a6a"),
    ("Caution", 26.7, "#e6c229"),
    ("Extreme Caution", 32.2, "#f18f01"),
    ("Danger", 39.4, "#d7263d"),
    ("Extreme Danger", 51.7, "#7b0828"),
]

FORECAST_HORIZONS = [1, 2, 3]        # days ahead

# Chronological split for the prediction model (local dates, inclusive).
SPLIT = {
    "train": ("2021-10-01", "2024-09-30"),
    "calibration": ("2024-10-01", "2025-09-30"),
    "test": ("2025-10-01", "2026-12-31"),
}
