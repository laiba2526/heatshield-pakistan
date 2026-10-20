---
title: HeatShield Pakistan
emoji: 🌡️
colorFrom: red
colorTo: yellow
sdk: docker
app_port: 7860
pinned: false
short_description: Heat-stress early warning for Karachi, Lahore and Jacobabad
---

# HeatShield Pakistan

Heat-stress early warning for **Karachi, Lahore and Jacobabad**. The project has five parts:

1. A Bronze → Silver → Gold data pipeline with two quality gates and a Data Quality Agent.
2. A daily maximum heat-index forecast for 1–3 days ahead, evaluated against persistence and historical-average baselines on an unseen year.
3. A RAG assistant that answers only from official NDMA / PDMA Sindh / PMD documents, with citations and "I don't know".
4. A Streamlit dashboard with hourly refresh, quality status and data freshness.
5. Packaging for Hugging Face Spaces.

> Student prototype, not an official warning service. Always follow PMD / NDMA / PDMA advisories.

## Quick start

```bash
python -m venv .venv && .venv\Scripts\activate        # Windows  (Linux/macOS: source .venv/bin/activate)
pip install -r requirements.txt
python run.py all          # = make -C src all: train, data, evaluate, rag-eval, reports, test
python run.py app          # dashboard on http://localhost:8501
```

`python run.py <target>` and `make -C src <target>` (the Makefile is `src/Makefile`) are equivalent. Use `run.py` on Windows, which has no `make`.

| Target | What it does |
|---|---|
| `data` | Rebuilds Silver and Gold from Bronze, runs Gate 1, the Data Quality Agent and Gate 2, and **promotes only if both gates pass** |
| `update` | The hourly refresh: fetches the latest Open-Meteo data (forecast + last 14 days), then runs `data` |
| `train` | Retrains the forecast model (chronological split, model selection on the calibration year), then runs `data` |
| `evaluate` | Model vs persistence vs historical average on the unseen test year: metrics, bootstrap CIs, interval coverage → `reports/model_evaluation.md` |
| `rag` / `rag-eval` | Builds the document index / evaluates citations and refusals → `reports/rag_evaluation.md` |
| `reports` | `reports/data_quality_report.md` and `data/missing_data_report.txt` |
| `drill` | Fault drill: corrupts data and tampers with a raw-file hash, then proves the trusted Gold data is unchanged |
| `app` | Starts the dashboard |
| `test` | Runs the test suite (35 tests) |

## Architecture

```
Bronze (raw, hashed in data/manifest.json)
  Open-Meteo archive + hourly forecasts · Copernicus ERA5 · NASA POWER · NDMA/PDMA/PMD PDFs
      │  Quality Gate 1: manifest SHA-256, JSON schema, variables, units, timestamps, hourly cadence
      ▼
Data Quality Agent  (src/heatshield/quality.py, run via src/quality_agent.py)
  fix: units, duplicates, RH overshoot, dew point · fill: ≤3 h interpolate, ≤24 h NASA POWER
  flag: long gaps, cross-source disagreement · quarantine: out-of-range, spikes, stuck values
      ▼
Silver  data/silver/*.parquet    hourly, °C / % / m/s, UTC, qc_flag per record
      ▼
Gold    data/gold/heat_daily.csv     one row per city × PKT day, row_id e.g. jacobabad-20250601
        data/gold/predictions.csv    model forecasts 1–3 days ahead with 80/90 % intervals
        data/gold/forecast_*.         Open-Meteo NWP forecast (hourly + daily)
      │  Quality Gate 2: completeness ≥95 %, quarantine ≤2 %, no time regression, no row loss,
      │                  unique row_ids, finite heat index, valid predictions, forecast ≥48 h
      ▼
promote → data/gold (trusted)        failed run → data/_staging/<run_id>; trusted data untouched
      ▼
Dashboard · RAG assistant · status (data/status) · audit log (data/audit) · quarantine (data/quarantine)
```

**Heat-stress indicator:** the NWS heat index (Rothfusz regression with the official low- and high-humidity adjustments). Risk levels use the NWS categories, in °C: Caution ≥ 26.7, Extreme Caution ≥ 32.2, Danger ≥ 39.4, Extreme Danger ≥ 51.7.

## Results (unseen test year 2025-10-01 → 2026-10-19)

| Horizon | Model MAE | Persistence | Historical average | Model − best baseline, 95 % CI | 90 % interval coverage |
|---|---|---|---|---|---|
| 1 day | **1.14 °C** | 1.16 | 2.02 | [−0.06, +0.03] (tie) | 90.1 % |
| 2 days | **1.53 °C** | 1.64 | 2.02 | [−0.18, +0.00] | 89.6 % |
| 3 days | **1.74 °C** | 1.98 | 2.02 | [−0.30, −0.08] (better) | 89.8 % |

RAG assistant, held-out test questions:

| Metric | Result |
|---|---|
| Retrieval hit@3 | 100 % |
| Expected fact in the answer | 93 % |
| False refusals | 0 % |
| Correct "I don't know" | 100 % |
| Data questions citing the right Gold row | 100 % |

Full details: [reports/model_evaluation.md](reports/model_evaluation.md), [reports/rag_evaluation.md](reports/rag_evaluation.md), [docs/model_card.md](docs/model_card.md), [reports/data_quality_report.md](reports/data_quality_report.md).

## Repository map

| Path | Content |
|---|---|
| `src/heatshield/` | `config` · `bronze` (Gate 1) · `quality` (Data Quality Agent) · `pipeline` (gates, staging, promotion, status) · `transform` (Gold) · `heat_index` · `baseline` · `features` · `model` · `evaluate` · `fetch` · `reports` · `drill` |
| `src/quality_agent.py`, `src/Makefile` | Member 3's Data Quality Agent entry point: `make -C src data` / `make -C src update` run through it, and `--file` checks any single hourly file. Writes `reports/validation_report.json` |
| `src/heatshield/rag/` | `ingest` (PDF → cited chunks) · `agent` (retrieval, refusal, answers, Gold-row citations) · `evaluate` |
| `app/streamlit_app.py` | Dashboard |
| `eval/rag_questions.json` | RAG evaluation questions (dev/test split) |
| `data/` | `bronze/`, `silver/`, `gold/`, `rag/`, `status/`, `audit/`, `quarantine/`, `manifest.json` |
| `reports/` | Generated evaluation and quality reports; `validation/` holds one JSON per run |
| `docs/` | `sources.md` (sources and licences), `model_card.md`, `DEPLOYMENT.md`, `handOffToAatiqaandYusra.md` (root) |
| `scripts/` | Member 1's fetch scripts, `deploy_hf.py` |

## Data and licences

Open-Meteo (CC BY 4.0), Copernicus ERA5 (CC BY 4.0, via Open-Meteo) and NASA POWER (free use with acknowledgement) are redistributed with attribution. The NDMA / PDMA / PMD documents are **not** openly licensed, so the public Space downloads them from the publishers at start-up instead of shipping them. See [docs/sources.md](docs/sources.md).
