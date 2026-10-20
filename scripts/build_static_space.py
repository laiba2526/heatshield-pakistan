"""Build the free *static* Hugging Face Space (Streamlit running in the browser).

Free Hugging Face accounts can only host static Spaces, so the dashboard runs
in the visitor's browser through stlite (Streamlit on Pyodide). The pipeline
itself (fetch -> quality gates -> Gold) runs hourly in GitHub Actions; this
script packs the latest *trusted* outputs and the app code into
``build/hf_static/``:

* ``index.html`` - loads stlite from the CDN and mounts the app
* ``app.zip``    - app code + trusted Gold/status/reports + prebuilt RAG index
* ``README.md``  - Space configuration (``sdk: static``)

Usage: ``python scripts/build_static_space.py`` (then ``scripts/deploy_hf.py``)
"""
import json
import shutil
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build" / "hf_static"
STLITE = "1.9.2"            # @stlite/browser release (Streamlit 1.62 on Pyodide)
REQUIREMENTS = ["pandas", "numpy", "scikit-learn", "plotly==5.24.1"]

CODE = [
    "app/streamlit_app.py",
    "src/heatshield/__init__.py", "src/heatshield/config.py", "src/heatshield/heat_index.py",
    "src/heatshield/bronze.py", "src/heatshield/rag/__init__.py", "src/heatshield/rag/agent.py",
    "src/heatshield/rag/ingest.py",
]
DATA = [
    "data/gold/heat_daily.csv", "data/gold/predictions.csv", "data/gold/forecast_daily.csv",
    "data/gold/source_agreement.csv", "data/status/run_status.json",
    "data/rag/chunks.jsonl", "data/rag/thresholds.json",
    "reports/model_evaluation.json", "reports/model_evaluation.md", "reports/model_test_predictions.csv",
    "reports/rag_evaluation.md", "reports/data_quality_report.md",
]
TAILS = {"data/status/run_history.jsonl": 200, "data/audit/audit_log.jsonl": 400}

INDEX = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>HeatShield Pakistan</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@stlite/browser@{stlite}/build/stlite.css" />
    <style>
      body {{ margin: 0; background: #ffffff; font-family: system-ui, sans-serif; }}
      #loading {{ max-width: 640px; margin: 18vh auto 0; padding: 0 16px; color: #444; text-align: center; }}
      @media (prefers-color-scheme: dark) {{ body {{ background: #0e1117; }} #loading {{ color: #ccc; }} }}
    </style>
  </head>
  <body>
    <div id="root">
      <div id="loading">
        <h2>🌡️ HeatShield Pakistan</h2>
        <p>Loading the dashboard in your browser… the first visit takes about a minute
           while Python and the data are downloaded.</p>
      </div>
    </div>
    <script type="module">
      import {{ mount }} from "https://cdn.jsdelivr.net/npm/@stlite/browser@{stlite}/build/stlite.js";
      mount(
        {{
          requirements: {requirements},
          entrypoint: "app/streamlit_app.py",
          archives: [{{ url: "./app.zip?v={stamp}", format: "zip", options: {{}} }}],
          streamlitConfig: {{ "client.toolbarMode": "viewer" }},
        }},
        document.getElementById("root"),
      );
    </script>
  </body>
</html>
"""

README = """---
title: HeatShield Pakistan
emoji: 🌡️
colorFrom: red
colorTo: yellow
sdk: static
app_file: index.html
pinned: false
short_description: Heat-stress early warning for Karachi, Lahore and Jacobabad
---

# HeatShield Pakistan

Heat-stress early warning for Karachi, Lahore and Jacobabad. The dashboard runs in the browser (Streamlit via stlite).
The data pipeline, with its two quality gates, runs hourly in GitHub Actions and publishes only trusted data here.

Source code, model card and reports: {repo}

Data: Open-Meteo.com (CC BY 4.0) · Contains modified Copernicus Climate Change Service information 2026 (ERA5)
· NASA POWER · guidance quoted from NDMA, PDMA Sindh and PMD documents with page citations.
Student prototype, not an official warning service.

Last data build: {stamp_h} UTC
"""


def build(repo_url: str = "https://github.com/laiba2526/heatshield-pakistan") -> Path:
    missing = [p for p in CODE + DATA if not (ROOT / p).exists()]
    if missing:
        raise SystemExit(f"missing inputs (run `python run.py all` first): {missing}")
    if not (ROOT / "data/gold/forecast_hourly.parquet").exists():
        raise SystemExit("missing data/gold/forecast_hourly.parquet (run `python run.py data` first)")
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")

    with zipfile.ZipFile(OUT / "app.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for rel in CODE + DATA:
            z.write(ROOT / rel, rel)
        # Parquet needs pyarrow, which the browser build does not install: ship CSV instead.
        fc = pd.read_parquet(ROOT / "data/gold/forecast_hourly.parquet")
        z.writestr("data/gold/forecast_hourly.csv", fc.to_csv(index=False))
        for rel, n in TAILS.items():
            path = ROOT / rel
            if path.exists():
                z.writestr(rel, "\n".join(path.read_text(encoding="utf-8").splitlines()[-n:]) + "\n")
        status = json.loads((ROOT / "data/status/run_status.json").read_text(encoding="utf-8"))
        run_id = status.get("last_success_run_id")
        report = ROOT / "reports" / "validation" / f"validation_{run_id}.json"
        if report.exists():
            z.write(report, f"reports/validation/{report.name}")

    (OUT / "index.html").write_text(
        INDEX.format(stlite=STLITE, requirements=json.dumps(REQUIREMENTS), stamp=stamp), encoding="utf-8")
    (OUT / "README.md").write_text(
        README.format(repo=repo_url, stamp_h=now.strftime("%Y-%m-%d %H:%M")), encoding="utf-8")
    size = (OUT / "app.zip").stat().st_size / 1e6
    print(f"built {OUT.relative_to(ROOT).as_posix()} (app.zip {size:.1f} MB, trusted run {run_id})")
    return OUT


if __name__ == "__main__":
    build()
    sys.exit(0)
