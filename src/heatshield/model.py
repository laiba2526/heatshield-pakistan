"""HeatShield prediction model: daily maximum heat index 1-3 days ahead.

Design
------
* One gradient-boosted tree model per horizon predicts the *anomaly* of the
  target day from its training-period climatology; the climatology is added
  back. Candidates (gradient boosting vs. ridge regression) are compared on the
  calibration year only - the test year is never used for any choice.
* Uncertainty: split-conformal prediction intervals. Absolute errors on the
  calibration year give per-(horizon, city) quantiles for 80 % and 90 %
  intervals; their empirical coverage is then checked on the unseen test year.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.impute import SimpleImputer

from heatshield import config
from heatshield.baseline import climatology_table
from heatshield.features import FEATURES, build_supervised

MODEL_PATH = config.MODELS / "heatshield_model.joblib"
META_PATH = config.MODELS / "model_meta.json"
SEED = 42
INTERVALS = (0.8, 0.9)


def _candidates() -> dict:
    return {
        "gradient_boosting": HistGradientBoostingRegressor(
            max_iter=400, learning_rate=0.04, max_leaf_nodes=24, min_samples_leaf=30,
            l2_regularization=1.0, random_state=SEED),
        "ridge": make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), Ridge(alpha=3.0)),
    }


def split_of(dates: pd.Series) -> pd.Series:
    out = pd.Series("unused", index=dates.index)
    for name, (lo, hi) in config.SPLIT.items():
        out[(dates >= lo) & (dates <= hi)] = name
    return out


def usable(df: pd.DataFrame) -> pd.DataFrame:
    return df[df["y"].notna() & df["hi_max_lag0"].notna() & df["clim_target"].notna()]


@dataclass
class HeatShieldModel:
    clim: pd.DataFrame
    models: dict = field(default_factory=dict)          # horizon -> fitted estimator
    chosen: dict = field(default_factory=dict)          # horizon -> candidate name
    conformal: dict = field(default_factory=dict)       # "h|city|level" -> half-width
    selection: dict = field(default_factory=dict)       # horizon -> {candidate: calib MAE}
    trained_through: str = ""

    # ---------------------------------------------------------------- training
    @classmethod
    def train(cls, daily: pd.DataFrame) -> "HeatShieldModel":
        daily = daily[daily["complete_day"]] if "complete_day" in daily else daily
        train_lo, train_hi = config.SPLIT["train"]
        train_daily = daily[(daily["date"] >= train_lo) & (daily["date"] <= train_hi)]
        m = cls(clim=climatology_table(train_daily), trained_through=train_hi)
        for h in config.FORECAST_HORIZONS:
            sup = usable(build_supervised(daily, m.clim, h))
            # The target date decides the split, so no training target lies in calibration/test.
            sp = split_of(sup["target_date"])
            tr, cal = sup[sp == "train"], sup[sp == "calibration"]
            scores, fitted = {}, {}
            for name, est in _candidates().items():
                est.fit(tr[FEATURES], tr["y"] - tr["clim_target"])
                pred = est.predict(cal[FEATURES]) + cal["clim_target"]
                scores[name] = float(np.mean(np.abs(pred - cal["y"])))
                fitted[name] = est
            best = min(scores, key=scores.get)
            m.models[h], m.chosen[h], m.selection[h] = fitted[best], best, scores
            resid = np.abs(m._raw_predict(h, cal) - cal["y"].to_numpy())
            for city in config.CITIES:
                r = resid[(cal["city"] == city).to_numpy()]
                for level in INTERVALS:
                    n = len(r)
                    q = np.quantile(r, min(1.0, np.ceil((n + 1) * level) / n)) if n else np.nan
                    m.conformal[f"{h}|{city}|{level}"] = float(q)
        return m

    # -------------------------------------------------------------- prediction
    def _raw_predict(self, h: int, X: pd.DataFrame) -> np.ndarray:
        return self.models[h].predict(X[FEATURES]) + X["clim_target"].to_numpy()

    def predict(self, sup: pd.DataFrame) -> pd.DataFrame:
        """Point forecast + conformal intervals for rows of ``build_supervised``."""
        out = []
        for h, grp in sup.groupby("horizon"):
            g = grp[grp["hi_max_lag0"].notna() & grp["clim_target"].notna()].copy()
            if g.empty:
                continue
            g["pred"] = self._raw_predict(int(h), g)
            for level in INTERVALS:
                w = g["city"].map(lambda c: self.conformal.get(f"{int(h)}|{c}|{level}", np.nan))
                tag = int(level * 100)
                g[f"lo{tag}"], g[f"hi{tag}"] = g["pred"] - w, g["pred"] + w
            out.append(g)
        return pd.concat(out, ignore_index=True) if out else pd.DataFrame()

    def forecast_from(self, daily: pd.DataFrame) -> pd.DataFrame:
        """Operational forecast: issue from each city's latest complete day."""
        rows = []
        daily = daily[daily["complete_day"]]
        for h in config.FORECAST_HORIZONS:
            sup = build_supervised(daily, self.clim, h)
            latest = sup.loc[sup.groupby("city")["issue_date"].idxmax()]
            rows.append(latest)
        return self.predict(pd.concat(rows, ignore_index=True))

    # ------------------------------------------------------------- persistence
    def save(self) -> None:
        config.MODELS.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, MODEL_PATH)
        META_PATH.write_text(json.dumps({
            "target": "daily maximum NWS heat index (deg C), local PKT day",
            "horizons_days": config.FORECAST_HORIZONS,
            "chosen_model_per_horizon": {str(k): v for k, v in self.chosen.items()},
            "calibration_mae_per_candidate": {str(k): v for k, v in self.selection.items()},
            "conformal_half_widths_c": self.conformal,
            "features": FEATURES,
            "split": config.SPLIT,
            "random_seed": SEED,
        }, indent=2), encoding="utf-8")

    @staticmethod
    def load() -> "HeatShieldModel | None":
        return joblib.load(MODEL_PATH) if MODEL_PATH.exists() else None
