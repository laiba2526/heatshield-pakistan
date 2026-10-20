import numpy as np
import pandas as pd
import pytest

from heatshield.quality import DataQualityAgent, dew_point_c


def hourly(n=240, start="2024-05-01", temp=None):
    ts = pd.date_range(start, periods=n, freq="h", tz="UTC")
    hours = np.arange(n)
    t = 35 + 6 * np.sin(2 * np.pi * hours / 24) if temp is None else temp
    df = pd.DataFrame({"timestamp_utc": ts, "temperature_c": t, "humidity_pct": 40.0, "wind_speed_ms": 3.0,
                       "source": "open_meteo_archive", "priority": 1, "bronze_file": "a.json"})
    df["dew_point_c"] = dew_point_c(df["temperature_c"], df["humidity_pct"])
    return df


def counts(agent):
    return agent.result(pd.DataFrame()).counts()


def test_clean_data_needs_no_action():
    agent = DataQualityAgent("t")
    out = agent.clean_city(hourly(), None, "x")
    assert (out["qc_flag"] == "ok").all()
    assert counts(agent) == {}


def test_out_of_range_is_quarantined_and_refilled():
    df = hourly()
    df.loc[100, "temperature_c"] = 999.0
    agent = DataQualityAgent("t")
    out = agent.clean_city(df, None, "x")
    res = agent.result(out)
    assert res.counts()["out_of_range"] == 1
    assert len(res.quarantine) == 1 and res.quarantine["temperature_c"].iloc[0] == 999.0   # original kept
    assert out.loc[100, "qc_flag"] == "filled_interp"
    assert 20 < out.loc[100, "temperature_c"] < 50


def test_humidity_overshoot_is_clipped():
    df = hourly()
    df.loc[5, "humidity_pct"] = 101.5
    agent = DataQualityAgent("t")
    out = agent.clean_city(df, None, "x")
    assert out.loc[5, "humidity_pct"] == 100.0
    assert counts(agent)["humidity_slightly_high"] == 1


def test_spike_removed():
    df = hourly()
    df.loc[50, "temperature_c"] += 15
    agent = DataQualityAgent("t")
    out = agent.clean_city(df, None, "x")
    assert counts(agent)["temperature_spike"] == 1
    assert abs(out.loc[50, "temperature_c"] - hourly().loc[50, "temperature_c"]) < 2


def test_stuck_sensor_quarantined():
    df = hourly()
    df.loc[60:75, "temperature_c"] = 30.0
    agent = DataQualityAgent("t")
    agent.clean_city(df, None, "x")
    assert counts(agent)["stuck_values"] == 16


def test_gap_filling_by_length():
    df = hourly(400)
    nasa = hourly(400).assign(temperature_c=33.0, source="nasa_power")
    drop = list(range(20, 22)) + list(range(100, 110)) + list(range(200, 240))   # 2 h, 10 h, 40 h gaps
    agent = DataQualityAgent("t")
    out = agent.clean_city(df.drop(index=drop), nasa, "x")
    assert (out.loc[20:21, "qc_flag"] == "filled_interp").all()
    assert (out.loc[100:109, "qc_flag"] == "filled_nasa").all()
    assert (out.loc[100:109, "temperature_c"] == 33.0).all()
    assert (out.loc[200:239, "qc_flag"] == "missing").all()       # too long: flagged, not invented
    c = counts(agent)
    assert c["short_gap"] == 2 and c["medium_gap"] == 10 and c["long_gap"] == 40


def test_overlapping_files_resolved_by_priority():
    a = hourly(48)
    b = hourly(48).assign(temperature_c=20.0, priority=0, source="open_meteo_recent", bronze_file="b.json")
    agent = DataQualityAgent("t")
    out = agent.clean_city(pd.concat([a, b]), None, "x")
    assert len(out) == 48
    assert out["source"].eq("open_meteo_archive").all()           # higher priority wins
    assert "duplicate_timestamp" not in counts(agent)
    assert counts(agent)["overlap_resolved"] == 48


def test_unit_fixes():
    agent = DataQualityAgent("t")
    df = hourly().assign(humidity_pct=0.4)
    assert agent.fix_units(df, "x", "s")["humidity_pct"].iloc[0] == pytest.approx(40.0)
    k = hourly().assign(temperature_c=lambda d: d["temperature_c"] + 273.15, dew_point_c=lambda d: d["dew_point_c"] + 273.15)
    fixed = agent.fix_units(k, "x", "s")
    assert fixed["temperature_c"].max() < 60
    assert {"unit_humidity_scale", "unit_temperature_k"} <= set(counts(agent))


def test_dew_point_recomputed_when_impossible():
    df = hourly()
    df.loc[10, "dew_point_c"] = df.loc[10, "temperature_c"] + 5
    agent = DataQualityAgent("t")
    out = agent.clean_city(df, None, "x")
    assert out.loc[10, "dew_point_c"] < out.loc[10, "temperature_c"]
    assert counts(agent)["dew_point_inconsistent"] == 1
