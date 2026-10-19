# HeatShield Data Pipeline — Member 2 Handoff Guide

This document outlines how to consume the cleaned weather data and computed heat indices produced by Member 2's pipeline for automation (Member 3) and dashboard visualization (Member 4).

---

## 📂 1. Data Directory Structure
Processed data moves through layers. You can access the final outputs directly:
* **Bronze Layer (Raw API JSONs):** `data/bronze/nasa_power/` & `data/bronze/open_meteo/`
* **Silver Layer (Cleaned Datasets):** `data/silver/`
* **Gold Layer (Final Metrics & Heat Indices):** `data/gold/`

---

## 🐍 2. How to Import and Use Pipeline Functions
If your automation or dashboard script needs to trigger or import the data transformations directly, ensure your script includes the local path fix and imports from `heatshield`:

```python
import sys
import os

# Ensure Python can find the src package
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), 'src')))

from heatshield.clean import clean_weather_data
from heatshield.transform import generate_gold_layer
from heatshield.quality import check_missing_values