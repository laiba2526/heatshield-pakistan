"""Model features for the daily maximum heat index forecast.

For an issue day ``t`` and horizon ``h`` (days) the target is ``hi_max_c`` on
day ``t + h``. Every feature uses information available at the end of day
``t`` only, and the climatology is fitted on training dates only, so no
feature can leak the future.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from heatshield.baseline import climatology_lookup

TARGET = "hi_max_c"
FEATURES = [
    "hi_max_lag0", "hi_max_lag1", "hi_max_lag2", "hi_max_lag3", "hi_max_lag6",
    "hi_max_roll3", "hi_max_roll7", "hi_max_std7", "hi_max_delta1",
    "tmax_lag0", "tmax_lag1", "tmin_lag0", "rh_mean_lag0", "rh_min_lag0",
    "dew_mean_lag0", "dew_mean_delta1", "wind_mean_lag0", "hours_danger_lag0",
    "clim_issue", "clim_target", "anom_lag0", "anom_roll3",
    "doy_sin", "doy_cos", "city_karachi", "city_lahore", "city_jacobabad",
]


def _per_city(daily: pd.DataFrame) -> pd.DataFrame:
    d = daily.sort_values("date").set_index("date")
    full = pd.date_range(d.index.min(), d.index.max(), freq="D")
    d = d.reindex(full)
    d.index.name = "date"
    hi = d[TARGET]
    out = pd.DataFrame(index=d.index)
    for lag in (0, 1, 2, 3, 6):
        out[f"hi_max_lag{lag}"] = hi.shift(lag)
    out["hi_max_roll3"] = hi.rolling(3, min_periods=2).mean()
    out["hi_max_roll7"] = hi.rolling(7, min_periods=5).mean()
    out["hi_max_std7"] = hi.rolling(7, min_periods=5).std()
    out["hi_max_delta1"] = hi - hi.shift(1)
    out["tmax_lag0"] = d["tmax_c"]
    out["tmax_lag1"] = d["tmax_c"].shift(1)
    out["tmin_lag0"] = d["tmin_c"]
    out["rh_mean_lag0"] = d["rh_mean_pct"]
    out["rh_min_lag0"] = d["rh_min_pct"]
    out["dew_mean_lag0"] = d["dew_point_mean_c"]
    out["dew_mean_delta1"] = d["dew_point_mean_c"] - d["dew_point_mean_c"].shift(1)
    out["wind_mean_lag0"] = d["wind_mean_ms"]
    out["hours_danger_lag0"] = d["hours_hi_ge_danger"]
    out[TARGET] = hi
    return out.reset_index()


def build_issue_features(daily: pd.DataFrame, clim: pd.DataFrame) -> pd.DataFrame:
    """One row per city and issue date with every horizon-independent feature."""
    parts = []
    for city, grp in daily.groupby("city"):
        f = _per_city(grp)
        f["city"] = city
        parts.append(f)
    f = pd.concat(parts, ignore_index=True)
    f["clim_issue"] = climatology_lookup(clim, f["city"], f["date"])
    f["anom_lag0"] = f["hi_max_lag0"] - f["clim_issue"]
    f["anom_roll3"] = f["hi_max_roll3"] - f["clim_issue"]
    for c in ("karachi", "lahore", "jacobabad"):
        f[f"city_{c}"] = (f["city"] == c).astype(float)
    return f


def build_supervised(daily: pd.DataFrame, clim: pd.DataFrame, horizon: int) -> pd.DataFrame:
    """Issue-day features joined with the target ``horizon`` days later."""
    f = build_issue_features(daily, clim)
    f = f.rename(columns={"date": "issue_date", TARGET: "hi_max_issue"})
    f["target_date"] = f["issue_date"] + pd.Timedelta(days=horizon)
    f["clim_target"] = climatology_lookup(clim, f["city"], f["target_date"])
    doy = f["target_date"].dt.dayofyear
    f["doy_sin"] = np.sin(2 * np.pi * doy / 365.25)
    f["doy_cos"] = np.cos(2 * np.pi * doy / 365.25)
    target = daily[["city", "date", TARGET]].rename(columns={"date": "target_date", TARGET: "y"})
    f = f.merge(target, on=["city", "target_date"], how="left")
    f["horizon"] = horizon
    return f
