# Model card: HeatShield daily maximum heat-index forecast

| | |
|---|---|
| **Task** | Forecast the daily maximum NWS heat index (°C) for the local Pakistan day (PKT), 1, 2 and 3 days ahead |
| **Cities** | Karachi, Lahore, Jacobabad |
| **Code** | `src/heatshield/features.py`, `model.py`, `baseline.py`, `evaluate.py` |
| **Artefacts** | `models/heatshield_model.joblib`, `models/model_meta.json` |
| **Reproduce** | `make -C src train && make -C src evaluate` (seed 42, deterministic) |
| **Version** | 1.0 (October 2026) |

## Intended use

The model supports a public-facing dashboard that shows whether the next three days are likely to reach Caution, Extreme Caution, Danger or Extreme Danger heat-index levels, together with an uncertainty range. It is a decision-support prototype. It is **not** an official warning; PMD / NDMA / PDMA advisories take precedence.

The model is not suitable for:
* individual medical decisions,
* locations other than the three grid points,
* lead times beyond 3 days.

## Data

* **Ground truth and inputs:** the Gold table `data/gold/heat_daily.csv`. It is built from the Open-Meteo historical archive (2021-10 → 2026-10-10) plus Open-Meteo's recent-days series. The heat index is computed hourly from temperature and humidity, then aggregated per PKT day. Days with fewer than 20 valid hours are excluded.
* **Chronological split** by *target* date, so no training target falls in a later period:

| Split | Dates | Used for |
|---|---|---|
| train | 2021-10-01 → 2024-09-30 | Model fitting and the climatology (historical-average baseline) |
| calibration | 2024-10-01 → 2025-09-30 | Choosing between candidate models and calibrating the conformal intervals |
| test | 2025-10-01 → 2026-10-20 | Reporting only; never used for any choice |

## Method

* **Features** (issue day *t*, all available by the end of day *t*):
  * heat-index lags (0, 1, 2, 3 and 6 days), 3- and 7-day rolling mean and spread, day-to-day change,
  * Tmax and Tmin, mean and minimum RH, dew point and its change, wind, hours at Danger level,
  * training-period climatology for the issue and target days, and the anomaly against it,
  * seasonal sin/cos terms and a city indicator.
* **Target:** the anomaly of the target day from its climatology; the climatology is added back afterwards.
* **Candidates:** gradient-boosted trees (`HistGradientBoostingRegressor`) and ridge regression. They are compared per horizon on calibration-year MAE. **Ridge won at every horizon** (1-day: 1.14 vs 1.19 °C), so ridge is deployed. The stronger non-linear model did not pay off with three years of training data.
* **Uncertainty:** split-conformal prediction intervals. The 80 % and 90 % quantiles of absolute calibration-year errors are computed per horizon and city.
* **Declared baselines:**
  * *Persistence:* the forecast for day *t + h* equals the heat index observed on day *t*.
  * *Historical average:* the training-period mean for the target day of year, per city, smoothed over ±7 days.

## Results on the unseen test year

| Horizon | Model MAE (95 % CI) | Persistence | Historical average | Model − best baseline (95 % CI) | 90 % interval coverage |
|---|---|---|---|---|---|
| 1 day | 1.13 (1.03–1.24) | 1.16 | 2.02 | −0.06 … +0.03 | 90.1 % |
| 2 days | 1.53 (1.39–1.69) | 1.64 | 2.02 | −0.18 … +0.01 | 89.6 % |
| 3 days | 1.74 (1.57–1.94) | 1.98 | 2.02 | −0.30 … −0.08 | 89.9 % |

* Confidence intervals come from a moving-block bootstrap: 7-day blocks over dates, 1,000 resamples.
* **What this means:**
  * The model clearly beats the historical average at all horizons.
  * It beats persistence by a statistically significant margin at 3 days.
  * At 1 day it **ties** with persistence: the confidence interval of the difference includes 0.
  * The 90 % intervals are well calibrated (89.6–90.1 % coverage).
  * The 80 % intervals are slightly narrow (78 %).
* **Danger-level detection** (heat index ≥ 39.4 °C), 1-day: probability of detection 0.90, false-alarm ratio 0.13, critical success index 0.80. Persistence scores 0.89 / 0.12 / 0.79.
* Per-city and hot-season numbers are in `reports/model_evaluation.md`.

## Limitations and risks

* **Ground truth** is gridded model or reanalysis output, not station observations. Errors measure skill against that dataset, and urban heat-island effects are not resolved.
* **Day 1 skill** comes almost entirely from persistence. The model uses no numerical weather prediction (NWP) input. The most promising improvement is MOS-style post-processing of Open-Meteo forecasts, trained on Open-Meteo's historical-forecast archive. The dashboard already shows the raw NWP forecast next to the model.
* **The heat index** assumes shade and light wind. Direct sun can add up to about 8 °C. In very dry Jacobabad conditions (RH < 13 %) the NWS adjustment lowers the index below the air temperature.
* **One test year** gives a limited number of Danger events, so read event scores together with the confidence intervals.
* **Operational issue date:** forecasts are issued from the latest *complete* observed day. Today's 1-day forecast is therefore made from yesterday, and the dashboard shows the lead time.

## Ethical considerations

Under-warning is the costly error, so the dashboard also shows the risk level at the upper end of the 90 % interval ("could reach …"). All data are public; no personal data are involved.
