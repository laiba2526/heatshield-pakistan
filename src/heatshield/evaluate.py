"""Evaluate the prediction model against the declared baselines on unseen data.

* Test set: every target date in the ``test`` split (config.SPLIT) - dates the
  model, its climatology, its model selection and its conformal calibration
  never saw.
* Baselines: persistence (tomorrow = today) and historical average
  (training-period climatology for the target day of year).
* Metrics: MAE, RMSE, bias, R^2, MAE skill score vs. each baseline, per
  horizon, per city and for the hot season (Apr-Sep).
* Uncertainty: moving-block bootstrap (7-day blocks, 1000 resamples) 95 %
  confidence intervals for MAE and for the MAE difference to the best
  baseline; empirical coverage and width of the 80 % / 90 % conformal intervals.
* Decision quality: Danger-or-worse (heat index >= 39.4 C) detection - POD,
  false alarm ratio, CSI - and risk-category accuracy.

Usage: ``python -m heatshield.evaluate`` (= make -C src evaluate)
"""
from __future__ import annotations

import json
import sys

import numpy as np
import pandas as pd

from heatshield import config
from heatshield.features import build_supervised
from heatshield.heat_index import risk_level
from heatshield.model import HeatShieldModel, split_of, usable

N_BOOT, BLOCK, SEED = 1000, 7, 7
DANGER_C = 39.4


def _metrics(y, p) -> dict:
    e = p - y
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    return {"n": int(len(y)), "mae": float(np.mean(np.abs(e))), "rmse": float(np.sqrt(np.mean(e ** 2))),
            "bias": float(np.mean(e)), "r2": float(1 - np.sum(e ** 2) / ss_tot) if ss_tot else float("nan")}


def _block_indices(n_days: int, rng) -> np.ndarray:
    starts = rng.integers(0, max(1, n_days - BLOCK + 1), size=int(np.ceil(n_days / BLOCK)))
    return (starts[:, None] + np.arange(BLOCK)[None, :]).ravel()[:n_days]


def bootstrap_ci(df: pd.DataFrame, cols: list[str]) -> dict:
    """Moving-block bootstrap over *dates* (all cities of a date move together),
    which respects the strong day-to-day autocorrelation of weather errors."""
    rng = np.random.default_rng(SEED)
    dates = np.sort(df["target_date"].unique())
    by_date = {d: g for d, g in df.groupby("target_date")}
    stats = {c: [] for c in cols}
    stats.update({f"{c}_minus_best_baseline": [] for c in cols if c == "model"})
    for _ in range(N_BOOT):
        sample = pd.concat([by_date[dates[i]] for i in _block_indices(len(dates), rng)], ignore_index=True)
        maes = {c: float(np.mean(np.abs(sample[c] - sample["y"]))) for c in cols}
        for c in cols:
            stats[c].append(maes[c])
        if "model" in maes:
            stats["model_minus_best_baseline"].append(maes["model"] - min(maes["persistence"], maes["climatology"]))
    return {k: [float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))] for k, v in stats.items()}


def danger_scores(y, p) -> dict:
    obs, fc = y >= DANGER_C, p >= DANGER_C
    hits, misses, fa = int((obs & fc).sum()), int((obs & ~fc).sum()), int((~obs & fc).sum())
    return {"observed_danger_days": int(obs.sum()), "hits": hits, "misses": misses, "false_alarms": fa,
            "pod": hits / (hits + misses) if hits + misses else None,
            "far": fa / (hits + fa) if hits + fa else None,
            "csi": hits / (hits + misses + fa) if hits + misses + fa else None}


def evaluate(daily: pd.DataFrame, model: HeatShieldModel) -> tuple[dict, pd.DataFrame]:
    daily = daily[daily["complete_day"]]
    rows = []
    for h in config.FORECAST_HORIZONS:
        sup = usable(build_supervised(daily, model.clim, h))
        test = sup[split_of(sup["target_date"]) == "test"]
        pred = model.predict(test)
        pred["persistence"] = pred["hi_max_lag0"]
        pred["climatology"] = pred["clim_target"]
        pred["model"] = pred["pred"]
        rows.append(pred)
    allp = pd.concat(rows, ignore_index=True)

    report = {"test_period": {"from": str(allp["target_date"].min().date()), "to": str(allp["target_date"].max().date())},
              "danger_threshold_c": DANGER_C, "horizons": {}}
    methods = ["model", "persistence", "climatology"]
    for h, g in allp.groupby("horizon"):
        hr = {"overall": {}, "by_city": {}, "hot_season_apr_sep": {}}
        for m in methods:
            hr["overall"][m] = _metrics(g["y"].to_numpy(), g[m].to_numpy())
            hr["overall"][m]["danger"] = danger_scores(g["y"].to_numpy(), g[m].to_numpy())
            hr["overall"][m]["risk_category_accuracy"] = float(np.mean(
                risk_level(g[m].to_numpy()) == risk_level(g["y"].to_numpy())))
        for base in ("persistence", "climatology"):
            hr["overall"][f"skill_vs_{base}"] = 1 - hr["overall"]["model"]["mae"] / hr["overall"][base]["mae"]
        hr["overall"]["bootstrap_95ci_mae"] = bootstrap_ci(g, methods)
        for level in (80, 90):
            inside = (g["y"] >= g[f"lo{level}"]) & (g["y"] <= g[f"hi{level}"])
            hr["overall"][f"interval_{level}"] = {"nominal": level / 100, "empirical_coverage": float(inside.mean()),
                                                 "mean_width_c": float((g[f"hi{level}"] - g[f"lo{level}"]).mean())}
        for city, gc in g.groupby("city"):
            hr["by_city"][city] = {m: _metrics(gc["y"].to_numpy(), gc[m].to_numpy()) for m in methods}
            hr["by_city"][city]["interval_90_coverage"] = float(((gc["y"] >= gc["lo90"]) & (gc["y"] <= gc["hi90"])).mean())
        hot = g[g["target_date"].dt.month.between(4, 9)]
        hr["hot_season_apr_sep"] = {m: _metrics(hot["y"].to_numpy(), hot[m].to_numpy()) for m in methods}
        for m in methods:
            hr["hot_season_apr_sep"][m]["danger"] = danger_scores(hot["y"].to_numpy(), hot[m].to_numpy())
        report["horizons"][str(int(h))] = hr
    report["chosen_model_per_horizon"] = {str(k): v for k, v in model.chosen.items()}
    report["calibration_mae_per_candidate"] = {str(k): v for k, v in model.selection.items()}
    keep = ["city", "issue_date", "target_date", "horizon", "y", "model", "persistence", "climatology",
            "lo80", "hi80", "lo90", "hi90"]
    return report, allp[keep]


def to_markdown(rep: dict) -> str:
    L = ["# Model evaluation — HeatShield heat-index forecast", "",
         f"*Generated by `make -C src evaluate`. Unseen test period: **{rep['test_period']['from']} → {rep['test_period']['to']}** "
         "(target dates never used for training, climatology, model selection or interval calibration).*", "",
         "Target: daily maximum NWS heat index (°C) per city and local (PKT) day, forecast 1–3 days ahead.", "",
         "## Headline: MAE (°C) with 95 % block-bootstrap confidence intervals", "",
         "| Horizon | HeatShield model | Persistence | Historical average | Skill vs persistence | Skill vs hist. avg | Model − best baseline (95 % CI) |",
         "|---|---|---|---|---|---|---|"]
    for h, hr in rep["horizons"].items():
        o, ci = hr["overall"], hr["overall"]["bootstrap_95ci_mae"]
        f = lambda m: f"{o[m]['mae']:.2f} [{ci[m][0]:.2f}, {ci[m][1]:.2f}]"
        d = ci["model_minus_best_baseline"]
        L.append(f"| {h} day | {f('model')} | {f('persistence')} | {f('climatology')} | "
                 f"{o['skill_vs_persistence']:+.1%} | {o['skill_vs_climatology']:+.1%} | [{d[0]:+.2f}, {d[1]:+.2f}] |")
    L += ["", "A negative upper bound in the last column means the model is better than the best baseline "
          "with 95 % confidence.", "", "## All metrics", "",
          "| Horizon | Method | n | MAE | RMSE | Bias | R² | Risk-category accuracy | Danger POD | Danger FAR | Danger CSI |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    fmt = lambda v: "–" if v is None else f"{v:.2f}"
    for h, hr in rep["horizons"].items():
        for m in ("model", "persistence", "climatology"):
            o = hr["overall"][m]
            dz = o["danger"]
            L.append(f"| {h} | {m} | {o['n']} | {o['mae']:.2f} | {o['rmse']:.2f} | {o['bias']:+.2f} | {o['r2']:.3f} | "
                     f"{o['risk_category_accuracy']:.1%} | {fmt(dz['pod'])} | {fmt(dz['far'])} | {fmt(dz['csi'])} |")
    L += ["", "## Uncertainty: conformal prediction intervals", "",
          "| Horizon | 80 % coverage | 80 % mean width | 90 % coverage | 90 % mean width |", "|---|---|---|---|---|"]
    for h, hr in rep["horizons"].items():
        a, b = hr["overall"]["interval_80"], hr["overall"]["interval_90"]
        L.append(f"| {h} | {a['empirical_coverage']:.1%} | {a['mean_width_c']:.2f} °C | "
                 f"{b['empirical_coverage']:.1%} | {b['mean_width_c']:.2f} °C |")
    L += ["", "## By city (MAE °C)", "", "| Horizon | City | Model | Persistence | Historical average | 90 % interval coverage |",
          "|---|---|---|---|---|---|"]
    for h, hr in rep["horizons"].items():
        for city, c in hr["by_city"].items():
            L.append(f"| {h} | {city.title()} | {c['model']['mae']:.2f} | {c['persistence']['mae']:.2f} | "
                     f"{c['climatology']['mae']:.2f} | {c['interval_90_coverage']:.1%} |")
    L += ["", "## Hot season only (April–September targets)", "",
          "| Horizon | Model MAE | Persistence MAE | Hist. avg MAE | Model Danger POD / FAR |", "|---|---|---|---|---|"]
    for h, hr in rep["horizons"].items():
        s = hr["hot_season_apr_sep"]
        dz = s["model"]["danger"]
        L.append(f"| {h} | {s['model']['mae']:.2f} | {s['persistence']['mae']:.2f} | {s['climatology']['mae']:.2f} | "
                 f"{fmt(dz['pod'])} / {fmt(dz['far'])} |")
    L += ["", "## Model selection (calibration year only)", "",
          "| Horizon | Chosen | Calibration MAE per candidate |", "|---|---|---|"]
    for h, ch in rep["chosen_model_per_horizon"].items():
        cand = ", ".join(f"{k}: {v:.3f}" for k, v in rep["calibration_mae_per_candidate"][h].items())
        L.append(f"| {h} | {ch} | {cand} |")
    L += ["", "## Caveats", "",
          "* Ground truth is Open-Meteo historical reanalysis-based weather, not station observations; "
          "errors therefore measure skill at reproducing that dataset.",
          "* One unseen year per city: Danger-day scores rest on a limited number of events — read them with the CIs in mind.",
          "* The heat index (NWS/Rothfusz) was designed for shaded, light-wind conditions; it is an indicator, not a health outcome.",
          ""]
    return "\n".join(L)


def main() -> int:
    model = HeatShieldModel.load()
    if model is None:
        print("No trained model - run `make -C src train` first.")
        return 1
    daily = pd.read_csv(config.GOLD / "heat_daily.csv", parse_dates=["date"])
    rep, preds = evaluate(daily, model)
    config.REPORTS.mkdir(parents=True, exist_ok=True)
    (config.REPORTS / "model_evaluation.json").write_text(json.dumps(rep, indent=2), encoding="utf-8")
    (config.REPORTS / "model_evaluation.md").write_text(to_markdown(rep), encoding="utf-8")
    preds.to_csv(config.REPORTS / "model_test_predictions.csv", index=False, date_format="%Y-%m-%d")
    for h, hr in rep["horizons"].items():
        o = hr["overall"]
        print(f"h={h}: MAE model {o['model']['mae']:.2f} | persistence {o['persistence']['mae']:.2f} | "
              f"hist.avg {o['climatology']['mae']:.2f} | 90% coverage {o['interval_90']['empirical_coverage']:.1%}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
