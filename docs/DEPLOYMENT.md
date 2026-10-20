# Deployment and automation

## 1. Hugging Face Spaces (Docker)

The repository root is a ready-made Docker Space. `README.md` carries the Space front-matter (`sdk: docker`, `app_port: 7860`), and the `Dockerfile` builds the app.

```bash
pip install huggingface_hub
set HF_TOKEN=hf_...                                   # write token from huggingface.co/settings/tokens
python scripts/deploy_hf.py <your-hf-username>/heatshield-pakistan
```

* `deploy_hf.py` creates the Space if needed and uploads the repository. It **excludes** the NDMA / PDMA / PMD PDFs and their extracted text, which are not openly licensed (see `docs/sources.md`). At start-up the container downloads them from the official URLs, checks their SHA-256 against `data/manifest.json`, and builds the index.
* No API keys or secrets are needed: the assistant quotes the documents verbatim and uses no language model.
* **Hourly refresh inside the Space:** a background thread runs `pipeline.run("update")` every `HEATSHIELD_REFRESH_MINUTES` (default 60). A run that fails a quality gate leaves the trusted data in place, and the dashboard shows the failure.
* Free Spaces go to sleep after about 48 h without visitors. The first visit wakes the Space, and the refresher catches up immediately because it checks the age of the last run.
* Open-Meteo's free tier limits are per IP address. Spaces share IPs, so if fetches start failing, the status strip shows "Stale" and the run history shows the fetch errors.

## 2. Hourly refresh on GitHub (optional)

`.github/workflows/hourly-refresh.yml` runs `make -C src update` every hour and commits:
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
