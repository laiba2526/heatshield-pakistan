import numpy as np
import pandas as pd

from heatshield import config
from heatshield.baseline import climatology_table, persistence_forecast
from heatshield.features import build_supervised
from heatshield.model import split_of


def synthetic_daily(days=900):
    dates = pd.date_range("2021-10-01", periods=days, freq="D")
    rows = []
    for city in config.CITIES:
        doy = dates.dayofyear.to_numpy()
        hi = 32 + 8 * np.sin(2 * np.pi * (doy - 100) / 365) + np.random.default_rng(1).normal(0, 1, days)
        rows.append(pd.DataFrame({"city": city, "date": dates, "hi_max_c": hi, "tmax_c": hi - 2, "tmin_c": hi - 12,
                                  "rh_mean_pct": 40.0, "rh_min_pct": 20.0, "dew_point_mean_c": 15.0,
                                  "wind_mean_ms": 3.0, "hours_hi_ge_danger": 0, "complete_day": True}))
    return pd.concat(rows, ignore_index=True)


def test_features_do_not_see_the_future():
    daily = synthetic_daily()
    clim = climatology_table(daily)
    base = build_supervised(daily, clim, 1)
    issue = pd.Timestamp("2023-06-15")
    changed = daily.copy()
    changed.loc[changed["date"] > issue, ["hi_max_c", "tmax_c", "dew_point_mean_c"]] += 25   # alter the future
    after = build_supervised(changed, clim, 1)
    pick = lambda f: f[(f["issue_date"] == issue)].drop(columns=["y"]).set_index("city").sort_index()
    pd.testing.assert_frame_equal(pick(base), pick(after))


def test_target_is_h_days_ahead():
    daily = synthetic_daily()
    sup = build_supervised(daily, climatology_table(daily), 3)
    row = sup[(sup["city"] == "lahore") & (sup["issue_date"] == "2022-07-01")].iloc[0]
    truth = daily[(daily["city"] == "lahore") & (daily["date"] == "2022-07-04")]["hi_max_c"].iloc[0]
    assert row["y"] == truth


def test_persistence_baseline():
    daily = synthetic_daily(30)
    p = persistence_forecast(daily, 2)
    r = p[(p["city"] == "karachi")].iloc[0]
    assert r["target_date"] - r["issue_date"] == pd.Timedelta(days=2)
    assert r["persistence"] == daily[(daily["city"] == "karachi")]["hi_max_c"].iloc[0]


def test_climatology_is_smooth_and_circular():
    clim = climatology_table(synthetic_daily())
    k = clim[clim["city"] == "karachi"].set_index("doy")["clim_mean"]
    assert k.notna().all() and len(k) == 365
    assert abs(k[1] - k[365]) < 2                    # wraps around the new year


def test_splits_are_disjoint_and_ordered():
    dates = pd.Series(pd.date_range("2021-10-01", "2026-10-10", freq="D"))
    s = split_of(dates)
    assert set(s.unique()) == {"train", "calibration", "test"}
    assert dates[s == "train"].max() < dates[s == "calibration"].min()
    assert dates[s == "calibration"].max() < dates[s == "test"].min()
