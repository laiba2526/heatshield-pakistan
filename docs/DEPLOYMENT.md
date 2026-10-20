# Deployment and automation

## 1. Hugging Face Spaces (free static Space)

**Live:** https://huggingface.co/spaces/NeuralPowerX/heatshield-pakistan

Free Hugging Face accounts can only host *static* Spaces (Docker and Gradio Spaces now need a PRO subscription). The dashboard therefore runs **in the visitor's browser** with stlite (Streamlit 1.62 on Pyodide, `@stlite/browser@1.9.2`), and the data pipeline runs in GitHub Actions.

```bash
pip install huggingface_hub
hf auth login                                          # once, with a *write* token
python scripts/deploy_hf.py NeuralPowerX/heatshield-pakistan
```

* `scripts/build_static_space.py` writes `build/hf_static/`:
  * `index.html` loads stlite and mounts the app.
  * `app.zip` (≈0.4 MB) holds the app code, the trusted Gold tables, status, audit tail, reports and the prebuilt RAG index.
  * `README.md` is the Space config (`sdk: static`).
* The first visit downloads Python and the packages into the browser, which takes 1–2 minutes (longer on slow connections). Later visits are faster.
* **Inside the browser** there is no background refresher and no network fetching. The Data quality tab says the data comes from the last trusted GitHub Actions run.
* **Licence note:** the static build ships the 96 short extracted passages of the NDMA / PDMA / PMD documents used for citations, but not the PDFs. See `docs/sources.md` §5.
* **Docker alternative** (full app with in-process hourly refresh) for PRO accounts: `python scripts/deploy_hf.py <user>/<space> --docker`. The `Dockerfile` is tested locally: `docker build -t heatshield-pakistan .` then `docker run -p 7860:7860 heatshield-pakistan`.

## 2. Hourly refresh on GitHub (optional)

`.github/workflows/hourly-refresh.yml` runs `make -C src update` every hour. After a successful run it publishes the new trusted data to the static Space. This needs the repository **secret** `HF_TOKEN` (a Hugging Face write token) and the repository **variable** `HF_SPACE` = `NeuralPowerX/heatshield-pakistan`; only the repository owner can add these. Each run also commits:
* the new Bronze forecast files and the manifest,
* the promoted Silver and Gold layers,
* the status, audit log, quarantine and validation reports.

A failed gate commits only the status and audit trail, never the rejected data. To push to the Space after each successful run, set the repository secret `HF_TOKEN` and the repository variable `HF_SPACE` (e.g. `user/heatshield-pakistan`).

Each hourly commit adds roughly 75 KB of Bronze JSON, so prune old `forecast_*.json` files after the demo period. The pipeline only reads the newest 72 per city.

## 3. Local hourly schedule (Windows)

```bat
schtasks /Create /SC HOURLY /TN HeatShieldRefresh /TR "\"D:\Weather Forecast\heatshield-pakistan\.venv\Scripts\python.exe\" \"D:\Weather Forecast\heatshield-pakistan\run.py\" update"
```

## 4. ERA5 directly from the Copernicus CDS (alternative route)

ERA5 is currently fetched through Open-Meteo (`models=era5`, no account needed; `heatshield.fetch.fetch_era5`). To use the official CDS instead:
1. Register at https://cds.climate.copernicus.eu.
2. Accept the CC BY licence on the dataset page.
3. Put your key in `~/.cdsapirc`.
4. Run `pip install cdsapi` and request `reanalysis-era5-single-levels` with the variables `2m_temperature`, `2m_dewpoint_temperature`, `10m_u_component_of_wind` and `10m_v_component_of_wind` for a small box around each city.

CDS ERA5 has no relative-humidity variable at single levels. Derive RH from temperature and dew point (Magnus formula, as in `heatshield.quality.dew_point_c`). CDS files are NetCDF/GRIB, so a new reader would be needed in `bronze.py`.
