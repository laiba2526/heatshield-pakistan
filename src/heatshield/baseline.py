import numpy as np
import pandas as pd


def calculate_historical_baseline(df):
    baseline = {}
    if 'temperature' in df.columns:
        baseline['mean_temperature'] = df['temperature'].mean()
    if 'humidity' in df.columns:
        baseline['mean_humidity'] = df['humidity'].mean()
    return baseline


def climatology_table(daily: pd.DataFrame, target: str = "hi_max_c", window: int = 7) -> pd.DataFrame:
    """Historical-average baseline: mean and spread of ``target`` per city and
    day-of-year, smoothed over a +/- ``window`` day circular window.

    Must be fitted on training dates only, otherwise the baseline leaks the future.
    """
    d = daily.dropna(subset=[target]).copy()
    d["doy"] = d["date"].dt.dayofyear.clip(upper=365)
    rows = []
    for city, grp in d.groupby("city"):
        by_doy = grp.groupby("doy")[target].agg(["sum", "count"]).reindex(range(1, 366), fill_value=0)
        sq = grp.assign(sq=grp[target] ** 2).groupby("doy")["sq"].sum().reindex(range(1, 366), fill_value=0)
        s, c, q = by_doy["sum"].to_numpy(float), by_doy["count"].to_numpy(float), sq.to_numpy(float)
        for doy in range(1, 366):
            idx = [(doy - 1 + k) % 365 for k in range(-window, window + 1)]
            n = c[idx].sum()
            mean = s[idx].sum() / n if n else np.nan
            var = q[idx].sum() / n - mean ** 2 if n else np.nan
            rows.append({"city": city, "doy": doy, "clim_mean": mean, "clim_std": float(np.sqrt(max(var, 0))), "n": int(n)})
    return pd.DataFrame(rows)


def climatology_lookup(clim: pd.DataFrame, cities: pd.Series, dates: pd.Series) -> np.ndarray:
    key = pd.DataFrame({"city": cities.to_numpy(), "doy": pd.to_datetime(dates).dt.dayofyear.clip(upper=365).to_numpy()})
    return key.merge(clim, on=["city", "doy"], how="left")["clim_mean"].to_numpy()


def persistence_forecast(daily: pd.DataFrame, horizon: int, target: str = "hi_max_c") -> pd.DataFrame:
    """Persistence baseline: the value at issue day t is the forecast for t + horizon."""
    d = daily[["city", "date", target]].copy()
    d["target_date"] = d["date"] + pd.Timedelta(days=horizon)
    return d.rename(columns={target: "persistence", "date": "issue_date"})
