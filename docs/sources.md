# HeatShield Pakistan — Data Sources

Licences and URLs were verified on **2026-10-20**, with the confirming URL given for each source. Raw files live in `data/bronze/`. Every file is recorded in `data/manifest.json` with its request URL, UTC download time, licence and SHA-256, and Quality Gate 1 rejects any file whose hash no longer matches.

| Source | Role in HeatShield | Licence | Redistribution |
|---|---|---|---|
| Open-Meteo historical archive | Primary hourly series 2021-10-01 → 2026-10-10 | CC BY 4.0 | Yes, with attribution |
| Open-Meteo forecast API | Hourly refresh: last 14 days + 4-day forecast | CC BY 4.0 | Yes, with attribution |
| Copernicus ERA5 (via Open-Meteo) | Independent reanalysis cross-check | CC BY 4.0 (since 2 Jul 2025) | Yes, with attribution |
| NASA POWER hourly | Cross-check and gap filling (≤ 24 h) | Free use, acknowledgement requested | Yes, with acknowledgement |
| NDMA / PDMA Sindh / PMD PDFs | RAG evidence only | No open licence ("All rights reserved") | **No**: cite and link, fetch from the publisher |

## 1. NASA POWER

* **Publisher:** NASA Langley Research Center, POWER Project. Docs: https://power.larc.nasa.gov/docs/
* **API:** https://power.larc.nasa.gov/api/temporal/hourly/point (community RE, UTC)
* **Data:** T2M, RH2M, T2MDEW, WS10M for Karachi, Lahore and Jacobabad, 2021–2025, one JSON per city-year (15 files).
* **Terms (verified):** NASA POWER's AWS Open Data Registry entry states that "there are no restrictions on the use, access, and/or download of data" and asks users to cite it (https://registry.opendata.aws/nasa-power/). The POWER docs site itself has no formal licence page.
* **Required acknowledgement** (https://power.larc.nasa.gov/docs/referencing/), used in the dashboard footer: *"The data was obtained from the National Aeronautics and Space Administration (NASA) Langley Research Center (LaRC) Prediction of Worldwide Energy Resource (POWER) Project funded through the NASA Earth Science Division."* Give the hourly API version and the access date (October 2026). The project also asks to be told by e-mail (larc-power-project@mail.nasa.gov) when its data is passed on to others.
* **Checks:** no `-999` fill values in any file; every variable is complete (`data/missing_data_report.txt`).
* **Limitations:** NASA POWER is gridded MERRA-2-based data at roughly 0.5°, not station observations. Its daily Tmax runs about 2 °C warmer than Open-Meteo in Lahore and Jacobabad (`data/gold/source_agreement.csv`).

## 2. Open-Meteo historical weather API

* **Docs:** https://open-meteo.com/en/docs/historical-weather-api. **Endpoint:** https://archive-api.open-meteo.com/v1/archive
* **Data:** temperature_2m, relative_humidity_2m, dew_point_2m and wind_speed_10m (km/h, converted to m/s in Silver), hourly in UTC, 2021-10-01 → 2026-10-10. Each city has 44,064 hours with no gaps.
* **Licence (verified):** "API data are offered under Attribution 4.0 International (CC BY 4.0)" (https://open-meteo.com/en/licence). The terms page confirms CC BY 4.0 (https://open-meteo.com/en/terms).
* **Attribution:** credit Open-Meteo, link to the licence, state any changes, and put a link next to any place the data are displayed. The dashboard shows "Weather data by Open-Meteo.com". Citation: Zippenfenig, P. (2023). *Open-Meteo.com Weather API*. Zenodo. doi:10.5281/ZENODO.7970649
* **Free-tier conditions:** non-commercial use only, under 10,000 calls/day, 5,000/hour and 600/minute per IP. The hourly refresh makes 72 calls/day.
* **Independence:** the default "best match" historical series blends ERA5, ERA5-Land and ECMWF IFS (9 km IFS from 2017), so it is **not independent of ERA5**.

## 3. Open-Meteo forecast API

* **Docs:** https://open-meteo.com/en/docs. **Endpoint:** https://api.open-meteo.com/v1/forecast
* **Requests:** the same variables with `past_days=14` and `forecast_days=4` (4 UTC days, so the third Pakistan day is complete), fetched every hour by `make -C src update`. The past part fills the 5–10 day delay before archive data is published. The future part is the NWP forecast shown on the dashboard.
* **Licence:** CC BY 4.0, as above. Some upstream national models carry their own licences. For example, UK Met Office data is CC BY-SA, though it is unlikely to feed the default model mix for Pakistan; this has not been verified.
* **Evaluation note:** forecast-API values are model output. They are labelled `open_meteo_recent` in Silver and never mixed silently with archive data.

## 4. Copernicus ERA5 (completed: previously "not downloaded")

* **Dataset:** ERA5 hourly data on single levels (https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels).
* **How it was obtained:** Open-Meteo historical API with `models=era5`, which gives pure 0.25° ERA5 rather than the blended default, for 2021-10-01 → 2026-10-10. Files are in `data/bronze/era5/era5_<city>_<stamp>.json` and have manifest entries. No CDS account is needed. Anyone with a CDS account can also use the official `cdsapi` route described in `docs/DEPLOYMENT.md`.
* **Licence (verified):** the CDS catalogue gives `"license": "CC-BY-4.0"` (https://cds.climate.copernicus.eu/licences/cc-by). C3S replaced the old "Licence to use Copernicus Products" with CC BY on **2 July 2025** (https://forum.ecmwf.int/t/cc-by-licence-to-replace-licence-to-use-copernicus-products-on-02-july-2025/13464).
* **Required attribution** (ECMWF guidance), used in the dashboard: *"Contains modified Copernicus Climate Change Service information 2026. Neither the European Commission nor ECMWF is responsible for any use that may be made of the Copernicus information or data it contains."* Citation: Hersbach, H. et al. (2023). *ERA5 hourly data on single levels from 1940 to present*. C3S CDS. doi:10.24381/cds.adbb2d47
* **Agreement with the primary series** (daily Tmax MAE): Karachi 1.48 °C, Lahore 1.17 °C, Jacobabad 1.31 °C, all with correlation ≥ 0.95. Some of this agreement comes from shared ERA5 heritage (see §2). NASA POWER (MERRA-2) is the more independent cross-check.

## 5. Official heat-safety documents (RAG evidence)

| File | Publisher | Official URL (HTTP 200 on 2026-10-20) | Pages used |
|---|---|---|---|
| `ndma_heatwave_advisory_apr2025.pdf` | NDMA (hosted on mocc.gov.pk) | https://mocc.gov.pk/SiteImage/Misc/files/NDMA%20Heatwave%20Advisory%20(25%20April%202025)%20Final.pdf | 1–5 (6–7 have no text layer) |
| `pdma_sindh_heatwave_alert_may2025.pdf` | PDMA Sindh; pages 3–4 are the **PMD Heatwave-Alert** with a 3-day Karachi forecast | https://pdma.gos.pk/Documents/Heatwave/Heatwave_2025/Heatwave_Alert_2025/Heatwave%20Alert%20Dated%2015-05-2025.pdf | 1–3 (page 4 is Urdu, text layer garbled) |
| `pdma_sindh_heatwave_sops.pdf` | PDMA Sindh | https://pdma.gos.pk/Documents/Reports/SOPs_Heatwave_Management_Sindh.pdf | 3–19 (1 cover, 2 contents, 20–22 image posters) |

* **PMD content:** the set has no stand-alone PMD PDF. The PMD alert of 15 May 2025 is embedded in the PDMA alert, and PMD's role is set out in SOP p. 9. PMD publishes its heatwave press releases at https://weather.gov.pk/nwfc/all-press-releases?type=HEAT%20WAVE (for example 06 May 2026 and 06 Jun 2026). These could be added later through `docs/document_urls.txt` and `scripts/fetch_all.py`.
* **Terms (verified):** none of these documents has an open licence.
  * NDMA's terms (https://www.ndma.gov.pk/terms-and-conditions) allow "personal, non-commercial use only" and prohibit unauthorised reproduction or distribution.
  * mocc.gov.pk, pdma.gos.pk and pmd.gov.pk show "All Rights Reserved" or plain copyright notices.
  * **Consequence:** the public Hugging Face Space does **not** ship the PDFs or their extracted text. At start-up it downloads them from the official URLs and accepts them only if the SHA-256 matches the manifest (`heatshield.rag.ingest.ensure_documents`). Answers quote short passages with citations and links back to the publisher. If the team wants to keep the PDFs in the public GitHub repo, it should ask NDMA / PDMA Sindh for permission first.
* **Note:** the SOP PDF's server `Last-Modified` date is April 2026, but its size and hash still match the copy downloaded in October 2026.
* **Use limitation:** the documents are guidance text only. They are never used as weather measurements or model training data.

## 6. Data integrity and provenance

* Raw bytes are saved exactly as received. Silver and Gold are always derived and never edited by hand.
* Quality Gate 1 recomputes every file's SHA-256 and rejects files that are missing from the manifest or have changed.
* Silver records carry `source`, `qc_flag` and `qc_notes`. Gold rows carry `row_id`, `sources`, `data_completeness` and `qc_status`. Dashboard and RAG answers cite Gold `row_id`s.
* Data-quality reports describe only the checks actually performed (`make -C src reports`).
