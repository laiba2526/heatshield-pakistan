"""Data quality checks (Member 2) and the Data Quality Agent (Member 3).

``check_missing_values`` / ``check_duplicates`` / ``check_humidity_bounds`` are
quick column checks. ``DataQualityAgent`` is the rule engine the pipeline uses.

A rule-based agent that inspects every hourly record before it may enter the
Silver layer and decides, per problem, to **fix**, **fill**, **flag** or
**quarantine**:

=====================  ============================================  ===========
rule                   detection                                     action
=====================  ============================================  ===========
unit_humidity_scale    a file's RH looks like a 0..1 fraction        fix (x100)
unit_temperature_k     a file's temperature looks like Kelvin        fix (-273.15)
duplicate_timestamp    same city/timestamp more than once            fix (keep newest)
humidity_slightly_high 100 < RH <= 103 (sensor/rounding overshoot)   fix (clip 100)
out_of_range           value outside physical limits                 quarantine + set missing
temperature_spike      >10 C jump that reverts the next hour         quarantine + set missing
stuck_values           temperature identical for >= 12 hours         quarantine + set missing
dew_point_inconsistent dew point > temperature + 1 C                 fix (recompute from T, RH)
short_gap              <= 3 missing hours                            fill (linear interpolation)
medium_gap             <= 24 missing hours                           fill (NASA POWER, same hour)
long_gap               > 24 missing hours                            flag (left missing)
cross_source           daily Tmax differs from NASA POWER by > 6 C   flag
=====================  ============================================  ===========

Every action is written to the audit log; every quarantined record (with its
original values) is written to ``data/quarantine/<run_id>/``. The agent never
deletes information silently.
"""

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from heatshield import config


# ------------------------------------------------- quick column checks
def check_missing_values(df):
    """Return count of missing values per column."""
    return df.isnull().sum()

def check_duplicates(df):
    """Return count of duplicate rows."""
    return df.duplicated().sum()

def check_humidity_bounds(rh_series):
    """Check if relative humidity values fall between 0 and 100."""
    return (rh_series >= 0) & (rh_series <= 100)


# ------------------------------------------------- Data Quality Agent
QC_OK, QC_FIXED, QC_INTERP, QC_NASA, QC_MISSING = "ok", "fixed", "filled_interp", "filled_nasa", "missing"


def dew_point_c(temp_c, rh_pct):
    """Magnus formula (Alduchov & Eskridge 1996 constants)."""
    a, b = 17.625, 243.04
    rh = np.clip(np.asarray(rh_pct, dtype=float), 1e-6, 100)
    gamma = np.log(rh / 100.0) + a * np.asarray(temp_c, dtype=float) / (b + np.asarray(temp_c, dtype=float))
    return b * gamma / (a - gamma)


@dataclass
class AgentResult:
    data: pd.DataFrame
    quarantine: pd.DataFrame
    actions: list = field(default_factory=list)

    def counts(self) -> dict:
        out: dict[str, int] = {}
        for a in self.actions:
            out[a["rule"]] = out.get(a["rule"], 0) + int(a["count"])
        return out


class DataQualityAgent:
    def __init__(self, run_id: str):
        self.run_id = run_id
        self.actions: list[dict] = []
        self.quarantined: list[pd.DataFrame] = []

    # ------------------------------------------------------------------ logging
    def _log(self, rule: str, action: str, city: str, mask_or_ts, reason: str, field_name: str = "") -> None:
        if isinstance(mask_or_ts, pd.Series):
            ts = mask_or_ts
        else:
            ts = pd.Series(mask_or_ts)
        count = int(len(ts))
        if count == 0:
            return
        sample = [str(t) for t in ts.head(10)]
        self.actions.append({
            "run_id": self.run_id, "stage": "data_quality_agent", "rule": rule, "action": action,
            "city": city, "field": field_name, "count": count, "sample_timestamps": sample, "reason": reason,
        })

    def _quarantine(self, rows: pd.DataFrame, rule: str, reason: str) -> None:
        if len(rows):
            q = rows.copy()
            q["qc_rule"] = rule
            q["qc_reason"] = reason
            q["run_id"] = self.run_id
            self.quarantined.append(q)

    # ------------------------------------------------------------ file level
    def fix_units(self, df: pd.DataFrame, city: str, source: str) -> pd.DataFrame:
        """Unit problems are a property of a whole file, so they are judged per file."""
        df = df.copy()
        rh = df["humidity_pct"].dropna()
        if len(rh) > 24 and rh.max() <= 1.0:
            df["humidity_pct"] = df["humidity_pct"] * 100
            self._log("unit_humidity_scale", "fix", city, df["timestamp_utc"],
                      f"{source}: humidity looked like a 0-1 fraction; multiplied by 100", "humidity_pct")
        t = df["temperature_c"].dropna()
        if len(t) > 24 and t.median() > 150:
            df["temperature_c"] = df["temperature_c"] - 273.15
            df["dew_point_c"] = df["dew_point_c"] - 273.15
            self._log("unit_temperature_k", "fix", city, df["timestamp_utc"],
                      f"{source}: temperature looked like Kelvin; converted to deg C", "temperature_c")
        return df

    # ---------------------------------------------------------- record level
    def clean_city(self, obs: pd.DataFrame, nasa: pd.DataFrame | None, city: str) -> pd.DataFrame:
        """Clean one city's hourly observations. ``obs`` may contain several sources."""
        obs = obs.sort_values(["timestamp_utc", "priority"], ascending=[True, False])

        dup = obs.duplicated("timestamp_utc", keep="first")
        if dup.any():
            # Overlap between files (archive vs. successive forecast issues) is by
            # design and resolved by priority; a timestamp repeated *inside one
            # file* is a data problem and is logged.
            in_file = obs.duplicated(["bronze_file", "timestamp_utc"], keep="first")
            self._log("duplicate_timestamp", "fix", city, obs.loc[in_file, "timestamp_utc"],
                      "timestamp repeated inside one Bronze file; kept one record")
            self._log("overlap_resolved", "fix", city, obs.loc[dup & ~in_file, "timestamp_utc"],
                      "hours present in several Bronze files; kept archive, else the newest forecast issue")
            obs = obs[~dup]

        full_index = pd.date_range(obs["timestamp_utc"].min(), obs["timestamp_utc"].max(), freq="h", tz="UTC")
        df = obs.set_index("timestamp_utc").reindex(full_index)
        df.index.name = "timestamp_utc"
        df["city"] = city
        df["qc_flag"] = np.where(df["temperature_c"].isna(), QC_MISSING, QC_OK)
        df["qc_notes"] = ""

        def note(mask, text, flag=None):
            df.loc[mask, "qc_notes"] = (df.loc[mask, "qc_notes"] + ";" + text).str.lstrip(";")
            if flag:
                df.loc[mask, "qc_flag"] = flag

        # Slight RH overshoot -> clip (fix).
        over = df["humidity_pct"].between(100, 103, inclusive="right")
        if over.any():
            self._log("humidity_slightly_high", "fix", city, df.index[over].to_series(),
                      "RH between 100 and 103 %; clipped to 100", "humidity_pct")
            df.loc[over, "humidity_pct"] = 100.0
            note(over, "rh_clipped", QC_FIXED)

        # Physical range -> quarantine + missing.
        for var, (lo, hi) in config.LIMITS.items():
            bad = df[var].notna() & ~df[var].between(lo, hi)
            if bad.any():
                self._quarantine(df[bad].reset_index(), "out_of_range", f"{var} outside [{lo}, {hi}]")
                self._log("out_of_range", "quarantine", city, df.index[bad].to_series(),
                          f"{var} outside physical range [{lo}, {hi}]; value set missing", var)
                df.loc[bad, var] = np.nan
                note(bad, f"{var}_out_of_range", QC_MISSING if var in ("temperature_c", "humidity_pct") else QC_FIXED)

        # Spikes: a big jump that immediately reverts.
        t = df["temperature_c"]
        d_prev, d_next = t - t.shift(1), t - t.shift(-1)
        spike = (d_prev.abs() > config.MAX_TEMP_STEP_C_PER_HOUR) & (d_next.abs() > config.MAX_TEMP_STEP_C_PER_HOUR) \
            & (np.sign(d_prev) == np.sign(d_next))
        if spike.any():
            self._quarantine(df[spike].reset_index(), "temperature_spike", "isolated jump > 10 C that reverts")
            self._log("temperature_spike", "quarantine", city, df.index[spike].to_series(),
                      "isolated temperature spike; value set missing and re-filled", "temperature_c")
            df.loc[spike, "temperature_c"] = np.nan
            note(spike, "spike_removed", QC_MISSING)

        # Stuck feed: identical temperature for a long run.
        t = df["temperature_c"]
        run_id = (t != t.shift()).cumsum()
        run_len = t.groupby(run_id).transform("size")
        stuck = t.notna() & (run_len >= config.STUCK_HOURS)
        if stuck.any():
            self._quarantine(df[stuck].reset_index(), "stuck_values", f"temperature constant for >= {config.STUCK_HOURS} h")
            self._log("stuck_values", "quarantine", city, df.index[stuck].to_series(),
                      f"temperature identical for >= {config.STUCK_HOURS} consecutive hours", "temperature_c")
            df.loc[stuck, ["temperature_c", "humidity_pct", "dew_point_c"]] = np.nan
            note(stuck, "stuck_removed", QC_MISSING)

        # Gap filling. Temperature and humidity are filled together.
        core = ["temperature_c", "humidity_pct"]
        missing = df[core].isna().any(axis=1)
        if missing.any():
            gap_id = (~missing).cumsum()
            gap_len = missing.groupby(gap_id).transform("sum")
            short = missing & (gap_len <= config.INTERPOLATE_MAX_GAP_H)
            if short.any():
                interp = df[core + ["dew_point_c", "wind_speed_ms"]].interpolate(method="time", limit_area="inside")
                for col in interp.columns:
                    df.loc[short, col] = df.loc[short, col].fillna(interp.loc[short, col])
                filled = short & df[core].notna().all(axis=1)
                self._log("short_gap", "fill", city, df.index[filled].to_series(),
                          f"gap <= {config.INTERPOLATE_MAX_GAP_H} h filled by time interpolation")
                df.loc[filled, "qc_flag"] = QC_INTERP
                df.loc[filled, "source"] = df.loc[filled, "source"].fillna("interpolated")

            medium = df[core].isna().any(axis=1) & (gap_len <= config.NASA_FILL_MAX_GAP_H)
            if medium.any() and nasa is not None and len(nasa):
                n = nasa.set_index("timestamp_utc")
                idx = df.index[medium].intersection(n.index)
                for col in ["temperature_c", "humidity_pct", "dew_point_c", "wind_speed_ms"]:
                    df.loc[idx, col] = df.loc[idx, col].fillna(n.loc[idx, col])
                ok = df.index.isin(idx) & df[core].notna().all(axis=1)
                self._log("medium_gap", "fill", city, df.index[ok].to_series(),
                          f"gap <= {config.NASA_FILL_MAX_GAP_H} h filled from NASA POWER at the same hour")
                df.loc[ok, "qc_flag"] = QC_NASA
                df.loc[ok, "source"] = "nasa_power_fill"

            still = df[core].isna().any(axis=1)
            if still.any():
                self._log("long_gap", "flag", city, df.index[still].to_series(),
                          "gap could not be filled; hours left missing and excluded from daily stats")
                df.loc[still, "qc_flag"] = QC_MISSING

        # Dew point consistency -> recompute from T and RH.
        bad_dew = df["dew_point_c"].isna() | (df["dew_point_c"] > df["temperature_c"] + 1.0)
        bad_dew &= df[core].notna().all(axis=1)
        if bad_dew.any():
            df.loc[bad_dew, "dew_point_c"] = dew_point_c(df.loc[bad_dew, "temperature_c"], df.loc[bad_dew, "humidity_pct"])
            self._log("dew_point_inconsistent", "fix", city, df.index[bad_dew].to_series(),
                      "dew point missing or above air temperature; recomputed with the Magnus formula", "dew_point_c")
            note(bad_dew, "dew_recomputed")
            df.loc[bad_dew & (df["qc_flag"] == QC_OK), "qc_flag"] = QC_FIXED

        return df.reset_index()

    def cross_check(self, silver: pd.DataFrame, nasa: pd.DataFrame, city: str) -> pd.DataFrame:
        """Flag local days whose Tmax disagrees strongly with NASA POWER."""
        if nasa is None or not len(nasa):
            return pd.DataFrame(columns=["city", "date", "tmax_primary", "tmax_nasa", "diff"])
        def daily_max(df):
            local = df.assign(date=df["timestamp_utc"].dt.tz_convert(config.LOCAL_TZ).dt.date)
            return local.groupby("date")["temperature_c"].max()
        both = pd.concat({"tmax_primary": daily_max(silver), "tmax_nasa": daily_max(nasa)}, axis=1).dropna()
        both["diff"] = both["tmax_primary"] - both["tmax_nasa"]
        bad = both[both["diff"].abs() > config.CROSS_SOURCE_TMAX_TOL_C]
        if len(bad):
            self._log("cross_source", "flag", city, pd.Series(bad.index.astype(str)),
                      f"daily Tmax differs from NASA POWER by more than {config.CROSS_SOURCE_TMAX_TOL_C} C")
        both["city"] = city
        return both.reset_index()

    def result(self, data: pd.DataFrame) -> AgentResult:
        q = pd.concat(self.quarantined, ignore_index=True) if self.quarantined else pd.DataFrame()
        return AgentResult(data=data, quarantine=q, actions=self.actions)
