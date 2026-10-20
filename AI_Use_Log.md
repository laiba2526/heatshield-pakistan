# AI use log

Every use of AI tools in the project goes here: what was asked, what was produced, and how a human checked it. Each team member adds their own entries.

| Date | Member | Tool | Task | Output used for | Human verification |
|---|---|---|---|---|---|
| 2026-10-20 | Member 4 (also covering Member 3 and the gaps from Members 1–2) | AI coding assistant | Review the repo; build the Data Quality Agent, quality gates, automation, model evaluation, RAG agent, dashboard and HF deployment; complete ERA5, licence checks, Silver/Gold, baselines and model | Most of `src/heatshield/`, `app/`, `tests/`, `eval/`, `docs/`, `reports/` | _To fill in: what you re-ran yourself (`make -C src all`, `make -C src drill`), which outputs you spot-checked, what you changed_ |

## Notes on what the AI did and did not do (2026-10-20 session)

* **Data:** downloaded ERA5 via the Open-Meteo API and fetched the latest Open-Meteo forecasts. Every file is recorded in the manifest with its hash. No existing raw file or hash was modified; licence text fields were updated after verification.
* **Licences:** checked against the publishers' web pages. The URLs and findings are in `docs/sources.md`. These are not legal advice.
* **Evaluation honesty:**
  * Model choices were made on the calibration year; the test year was used only for reporting.
  * The RAG decision *rule* and synonym list were refined while looking at failures across all questions. Only the numeric thresholds were fitted strictly on dev, so the RAG test numbers are somewhat optimistic (stated in the report).
  * Seven questions were added to the dev split after a smoke test. The test split was not changed.
* **Bugs the AI found and fixed in existing code:**
  * `.gitignore` had a broken `**pycache**` pattern.
  * The missing-data report was saved as UTF-16.
  * `heat_index_f` lacked the NWS humidity adjustments (the original tests still pass).
* **Tests:** two of the AI's own test expectations were initially wrong. They were corrected against hand calculations, not by changing the code to match.
