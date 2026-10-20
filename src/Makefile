# HeatShield Pakistan - pipeline automation (Member 3).
#   From the repo root:  make -C src data      (or: python run.py data, which also works on Windows)
#   From src/:           make data

ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/..)
PY ?= python
RUN = cd "$(ROOT)" && PYTHONPATH=src $(PY)

.PHONY: help all install era5 data update quality train evaluate rag rag-eval reports drill app test clean

help:
	@echo "make -C src install    install Python dependencies"
	@echo "make -C src era5       re-download Copernicus ERA5 (via Open-Meteo) into Bronze"
	@echo "make -C src data       rebuild Silver + Gold from Bronze, both quality gates, promote if valid"
	@echo "make -C src update     hourly refresh: fetch latest Open-Meteo data, then 'data'"
	@echo "make -C src quality FILE=path.csv   check one hourly file with the Data Quality Agent"
	@echo "make -C src train      retrain the forecast model (and rebuild Gold)"
	@echo "make -C src evaluate   evaluate the model vs baselines on the unseen test year"
	@echo "make -C src rag        build the document index for the RAG assistant"
	@echo "make -C src rag-eval   evaluate citations and I-don't-know behaviour"
	@echo "make -C src reports    missing-data + data-quality reports"
	@echo "make -C src drill      fault drill: prove bad data cannot replace trusted data"
	@echo "make -C src app        start the dashboard on http://localhost:8501"
	@echo "make -C src test       run the test suite"
	@echo "make -C src all        train, data, evaluate, rag-eval, reports, test"

all: train data evaluate rag-eval reports test

install:
	$(RUN) -m pip install -r requirements.txt

era5:
	$(RUN) -m heatshield.fetch

# Bronze -> Gate 1 -> Data Quality Agent -> Silver -> Gold -> Gate 2 -> promote (or keep last trusted)
data:
	$(RUN) src/quality_agent.py

# Hourly refresh: fetch the latest Open-Meteo data first, then the same checks
update:
	$(RUN) src/quality_agent.py --update

# Check one file: make -C src quality FILE=path/to/hourly.csv
quality:
	$(RUN) src/quality_agent.py --file "$(FILE)"

train:
	$(RUN) -m heatshield.pipeline train

evaluate:
	$(RUN) -m heatshield.evaluate

rag:
	$(RUN) -m heatshield.rag.ingest

rag-eval: rag
	$(RUN) -m heatshield.rag.evaluate

reports:
	$(RUN) scripts/check_missing_data.py
	$(RUN) -m heatshield.reports

# Fault drill: prove that invalid data cannot replace the trusted data
drill:
	$(RUN) -m heatshield.drill

app:
	$(RUN) -m streamlit run app/streamlit_app.py

test:
	$(RUN) -m pytest -q

# Removes only scratch output of failed runs; the audit log and quarantine are evidence and are kept
clean:
	rm -rf "$(ROOT)/data/_staging"
