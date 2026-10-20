# HeatShield Pakistan — Team Handoff Guide

This guide explains how to use the data, the quality checks, the model and the dashboard (originally Member 2's handoff to Aatiqa and Yusra, Members 3 and 4). It also says who verifies what on Day 3.

---

## 📂 1. Data directory structure

| Layer | Path | Content |
|---|---|---|
| Bronze (raw, hashed in `data/manifest.json`) | `data/bronze/open_meteo/`, `data/bronze/era5/`, `data/bronze/nasa_power/`, `data/bronze/documents/` | API JSON exactly as downloaded; official PDFs |
| Silver (cleaned, hourly) | `data/silver/weather_hourly.parquet`, `forecast_hourly.parquet`, `era5_hourly.parquet`, `nasa_power_hourly.parquet` | °C / % / m/s, UTC, `qc_flag` per record |
| Gold (final metrics) | `data/gold/heat_daily.csv` | one row per city and PKT day, with heat index, risk level and `row_id` (e.g. `jacobabad-20250601`) |
| Gold (forecasts) | `data/gold/predictions.csv`, `forecast_daily.csv`, `forecast_hourly.parquet` | model forecast with 80/90 % ranges; Open-Meteo NWP forecast |
| Status and evidence | `data/status/`, `data/audit/`, `data/quarantine/`, `reports/` | last run, freshness, audit log, quarantined records, reports |

Rebuild everything with `python run.py data` (or `make -C src data`).

---

## 🐍 2. How to import and use the pipeline functions

```python
import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "src")))

import pandas as pd
from heatshield.heat_index import heat_index_c, risk_level      # heat index in °C, NWS risk level
from heatshield.quality import DataQualityAgent, check_missing_values
from heatshield import pipeline                                 # pipeline.run("data") / pipeline.read_status()

daily = pd.read_csv("data/gold/heat_daily.csv", parse_dates=["date"])
status = pipeline.read_status()          # last run, last successful run, freshness per city
```

The older helpers `heatshield.clean.clean_weather_data` and `heatshield.transform.generate_gold_layer` still work (see `test_integration.py`). The pipeline itself uses `pipeline.run()`.

---

This document covers the status after the October 2026 integration work. Members 3 and 4's components were built together with the missing parts of Members 1 and 2.

## What was added or completed

| Owner role | Item | Where |
|---|---|---|
| Member 1 | ERA5 downloaded (via Open-Meteo `models=era5`) with manifest entries | `data/bronze/era5/`, `heatshield.fetch.fetch_era5` |
| Member 1 | Licences and URLs verified with sources; manifest licence fields updated (hashes untouched) | `docs/sources.md`, `data/manifest.json` |
| Member 1 | PMD content identified (PMD alert inside the PDMA alert, PMD press-release page) | `docs/sources.md` §5 |
| Member 1 | Missing-data report redone on every variable; original re-encoded to UTF-8 | `data/missing_data_report.txt`, `data/missing_data_report.txt` |
| Member 2 | Silver layer (standardised units, UTC, `qc_flag` per record) | `data/silver/` |
| Member 2 | Gold layer with heat index, risk level and stable `row_id` | `data/gold/heat_daily.csv` |
| Member 2 | Heat index: official NWS low- and high-humidity adjustments added; Celsius and risk helpers | `heat_index.py` (original API and tests kept) |
| Member 2 | Persistence and historical-average baselines, features, runnable model | `baseline.py`, `features.py`, `model.py` |
| Member 3 | Data Quality Agent (fix / fill / flag / quarantine) | `src/heatshield/quality_agent.py` (rules), `src/quality_agent.py` + `src/Makefile` (Member 3's entry point, upgraded to run the full pipeline and to check single files; the fixed 50 % humidity fill was replaced by interpolation / NASA POWER gap filling) |
| Member 3 | Quality Gates 1 and 2, validation reports, audit log, quarantine, staging and promotion | `bronze.py`, `pipeline.py` |
| Member 3 | `make -C src data` / `make -C src update`, hourly refresh, freshness tracking, last-trusted preservation, fault drill | `Makefile`, `run.py`, `pipeline.py`, `drill.py` |
| Member 4 | Evaluation vs baselines on the unseen year, bootstrap CIs, conformal intervals | `evaluate.py`, `reports/model_evaluation.md` |
| Member 4 | RAG Insight Agent with citations, Gold-row citations and "I don't know"; evaluation | `rag/`, `eval/rag_questions.json`, `reports/rag_evaluation.md` |
| Member 4 | Dashboard (forecast, risk, quality status, freshness, last successful run, chat) | `app/streamlit_app.py` |
| Member 4 | Hugging Face Spaces packaging | `Dockerfile`, `scripts/deploy_hf.py`, `docs/DEPLOYMENT.md` |

## Day-3 verification checklist

* **Member 1:**
  * `make -C src reports`, then check `data/missing_data_report.txt`.
  * Open three random manifest entries and confirm the URL, licence and hash (Gate 1 re-hashes everything).
  * In the dashboard chat, ask "What was the heat index in Karachi on 2024-06-24?" and confirm that the cited row `karachi-20240624` matches `data/gold/heat_daily.csv`.
* **Member 2:**
  * `make -C src test` (heat-index unit tests with hand-calculated values).
  * Run `make -C src train && make -C src evaluate` twice and confirm the numbers are identical.
  * Read `docs/model_card.md`.
* **Member 3:**
  * `make -C src drill`: both drills must print PASS, the Gold hash must be unchanged, and the failure must be visible in the dashboard's Data quality tab.
  * `make -C src update` with the network off: the run is recorded, the status turns stale, and the trusted data is kept.
* **Member 4:**
  * `make -C src rag-eval`.
  * Ask an unsupported question in the dashboard (it should answer "I don't know").
  * Deploy with `scripts/deploy_hf.py` and check the Space logs.
* **All:**
  * Run `make -C src all` from a fresh clone.
  * Tag `v1.0-final`.
  * Build `Summary.pdf` from README, model card and reports.
  * Complete `AI_Use_Log.md`.

## Open decisions for the team

1. **PDFs in the public GitHub repo.** The NDMA terms prohibit redistribution, so either remove `data/bronze/documents/*.pdf` from the public repo (the code can fetch them) or ask the publishers for permission.
2. **PMD press releases.** Add them to the RAG corpus? They are HTML pages, so they would need an HTML ingester.
3. **A day-1 model that beats persistence.** This needs NWP input (MOS on the Open-Meteo historical-forecast API); see the model card.
