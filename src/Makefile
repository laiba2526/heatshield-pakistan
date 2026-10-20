.PHONY: all data clean quality

all: data

data:
	@echo "=== Step 1: Running Data Ingestion (Bronze Layer) ==="
	@mkdir -p data/bronze data/silver data/gold logs data/quarantine

	@echo "=== Step 2: Processing Silver Layer ==="

	@echo "=== Step 3: Executing Data Quality Agent & Validation Gates ==="
	python src/quality_agent.py

	@echo "=== Pipeline rebuild complete successfully! ==="

clean:
	@echo "Cleaning caches..."
	rm -rf data/quarantine/*.csv logs/*.jsonl
