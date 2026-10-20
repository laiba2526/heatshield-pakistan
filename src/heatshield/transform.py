import numpy as np
import pandas as pd

from heatshield import config
from heatshield.clean import clean_weather_data
from heatshield.heat_index import heat_index_c, risk_level

MIN_HOURS_FOR_COMPLETE_DAY = 20


def generate_gold_layer(df):
    """Simple helper: renamed columns + heat index in deg C (same unit as ``temperature``)."""
    df = clean_weather_data(df)
    if 'temperature' in df.columns and 'humidity' in df.columns:
        df['heat_index'] = heat_index_c(df['temperature'].values, df['humidity'].values)
    return df


def add_hourly_heat_index(df: pd.DataFrame) -> pd.DataFrame:
    """Hourly heat index (deg C) and risk level on a Silver-schema frame."""
    df = df.copy()
    df["heat_index_c"] = heat_index_c(df["temperature_c"].to_numpy(), df["humidity_pct"].to_numpy())
    df["risk_level"] = risk_level(df["heat_index_c"].to_numpy())
    df["local_time"] = df["timestamp_utc"].dt.tz_convert(config.LOCAL_TZ)
    df["date"] = df["local_time"].dt.date
    return df


def daily_heat_table(hourly: pd.DataFrame, id_prefix: str = "") -> pd.DataFrame:
    """Aggregate hourly Silver data to one row per city and local (PKT) day.

    ``row_id`` is stable and human readable (``jacobabad-20250601``) so that
    dashboard insights and RAG answers can cite the exact Gold row.
    """
    h = add_hourly_heat_index(hourly)
    valid = h["temperature_c"].notna() & h["humidity_pct"].notna()
    h["valid"] = valid
    h["filled"] = h["qc_flag"].isin(["filled_interp", "filled_nasa"]) if "qc_flag" in h else False
    h["hi_ge_danger"] = h["heat_index_c"] >= 39.4
    g = h.groupby(["city", "date"])
    daily = pd.DataFrame({
        "tmax_c": g["temperature_c"].max(),
        "tmin_c": g["temperature_c"].min(),
        "tmean_c": g["temperature_c"].mean(),
        "rh_mean_pct": g["humidity_pct"].mean(),
        "rh_min_pct": g["humidity_pct"].min(),
        "dew_point_mean_c": g["dew_point_c"].mean(),
        "wind_mean_ms": g["wind_speed_ms"].mean(),
        "hi_max_c": g["heat_index_c"].max(),
        "hi_mean_c": g["heat_index_c"].mean(),
        "hours_hi_ge_danger": g["hi_ge_danger"].sum(),
        "valid_hours": g["valid"].sum(),
        "filled_hours": g["filled"].sum(),
        "hours": g.size(),
        "sources": g["source"].agg(lambda s: "+".join(sorted(set(map(str, s.dropna()))))),
    }).reset_index()
    daily["data_completeness"] = (daily["valid_hours"] / 24).clip(upper=1).round(3)
    daily["complete_day"] = daily["valid_hours"] >= MIN_HOURS_FOR_COMPLETE_DAY
    daily.loc[~daily["complete_day"], ["hi_max_c", "hi_mean_c", "tmax_c", "tmin_c"]] = np.nan
    daily["risk_level"] = risk_level(daily["hi_max_c"].to_numpy())
    daily["qc_status"] = np.select(
        [~daily["complete_day"], daily["filled_hours"] > 0], ["incomplete", "contains_filled_hours"], "ok")
    daily["date"] = pd.to_datetime(daily["date"])
    daily.insert(0, "row_id", id_prefix + daily["city"] + "-" + daily["date"].dt.strftime("%Y%m%d"))
    num = daily.select_dtypes("float").columns
    daily[num] = daily[num].round(2)
    return daily.sort_values(["city", "date"]).reset_index(drop=True)
