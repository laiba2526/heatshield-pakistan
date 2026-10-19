# HeatShield Pakistan — Data Sources

## 1. NASA POWER

* **Publisher:** NASA Langley Research Center — POWER Project
* **Official documentation:** https://power.larc.nasa.gov/docs/
* **API endpoint:** https://power.larc.nasa.gov/api/temporal/hourly/point
* **Data collected:** Temperature at 2 m (T2M), relative humidity at 2 m (RH2M), dew point at 2 m (T2MDEW), and wind speed at 10 m (WS10M).
* **Locations:** Karachi, Lahore, and Jacobabad, Pakistan.
* **Period requested:** 2021–2025, in yearly files.
* **Format:** JSON
* **Licence and usage:** Consult the official NASA POWER documentation and applicable data-source terms. Cite NASA POWER when using its data.
* **Limitations:** NASA POWER data are gridded environmental data, not necessarily measurements from a weather station located within each city.

## 2. Open-Meteo Historical Weather API

* **Publisher:** Open-Meteo
* **Official API documentation:** https://open-meteo.com/en/docs/historical-weather-api
* **Terms of use:** https://open-meteo.com/en/terms
* **API endpoint:** https://archive-api.open-meteo.com/v1/archive
* **Data collected:** The hourly variables configured in `scripts/fetch_open_meteo.py`.
* **Locations:** Karachi, Lahore, and Jacobabad, Pakistan.
* **Period requested:** 2021-10-01 to 2026-10-10.
* **Format:** JSON
* **Licence:** CC BY 4.0, subject to the applicable terms.
* **Attribution:** Credit Open-Meteo, link to the licence, and indicate modifications where applicable.
* **Important limitation:** Historical data include reanalysis products. Open-Meteo historical data may use ERA5 or other underlying weather products, so this source should not automatically be treated as independent of ERA5.

## 3. Open-Meteo Forecast API

* **Publisher:** Open-Meteo
* **Official documentation:** https://open-meteo.com/en/docs
* **Terms of use:** https://open-meteo.com/en/terms
* **API endpoint:** https://api.open-meteo.com/v1/forecast
* **Locations:** Karachi, Lahore, and Jacobabad, Pakistan.
* **Forecast period requested:** Three days.
* **Format:** JSON
* **Licence:** CC BY 4.0, subject to the applicable terms.
* **Attribution:** Credit Open-Meteo, link to the licence, and indicate modifications where applicable.
* **Purpose:** Forecast information for the prototype. Forecast data should be distinguished from historical observations or reanalysis data during evaluation.

## 4. NDMA / PDMA Heatwave Documents

* **Files collected:**

  * `ndma_heatwave_advisory_apr2025.pdf`
  * `pdma_sindh_heatwave_alert_may2025.pdf`
  * `pdma_sindh_heatwave_sops.pdf`
* **Purpose:** Public heat-safety guidance and supporting evidence for the retrieval-augmented generation (RAG) assistant.
* **Original publisher and document URL:** Verify each document against `docs/document_urls.txt` and the original publisher's website.
* **Licence and reuse terms:** Verify the terms applicable to each document. Do not assume that a publicly accessible PDF has an open licence.
* **Limitations:** Use these documents as supporting references. Do not treat their text as weather measurements or model-training data without a justified and permitted use.

## 5. ERA5 Status

* **Status:** No ERA5 files are currently recorded in `data/bronze/era5`.
* **Important:** ERA5 is not included as a downloaded dataset at this stage.
* **Independence consideration:** Open-Meteo historical data may be based on ERA5. Check the underlying products before claiming that two sources are independent.

## 6. Data Integrity and Provenance

* Raw data are stored under `data/bronze/`.
* File hashes and download metadata are recorded in `data/manifest.json`.
* Each manifest entry should identify the actual publisher, source URL, download time, file path, SHA-256 hash, and applicable licence.
* Do not invent missing source metadata or alter hashes to make the manifest appear complete.
* Data-quality reports describe only the checks actually performed.
* Before modeling, validate date coverage, missing values, variable units, and source overlap.

## ERA5 Status

- **Official dataset:** https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels
- **Status:** Not downloaded.
- **Purpose:** Potential future use for historical weather analysis.