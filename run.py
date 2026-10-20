"""Cross-platform stand-in for `make -C src <target>` (Windows has no make by default).

    python run.py data | update | train | evaluate | rag | rag-eval | reports | drill | app | test | all
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TARGETS = {
    "era5": [["-m", "heatshield.fetch"]],
    "data": [["src/quality_agent.py"]],
    "update": [["src/quality_agent.py", "--update"]],
    "train": [["-m", "heatshield.pipeline", "train"]],
    "evaluate": [["-m", "heatshield.evaluate"]],
    "rag": [["-m", "heatshield.rag.ingest"]],
    "rag-eval": [["-m", "heatshield.rag.ingest"], ["-m", "heatshield.rag.evaluate"]],
    "reports": [["scripts/check_missing_data.py"], ["-m", "heatshield.reports"]],
    "drill": [["-m", "heatshield.drill"]],
    "app": [["-m", "streamlit", "run", "app/streamlit_app.py"]],
    "test": [["-m", "pytest", "-q"]],
}
TARGETS["all"] = TARGETS["train"] + TARGETS["data"] + TARGETS["evaluate"] + TARGETS["rag-eval"] + TARGETS["reports"] + TARGETS["test"]

if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in TARGETS:
        print(__doc__)
        sys.exit(2)
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), PYTHONIOENCODING="utf-8")
    for args in TARGETS[sys.argv[1]]:
        code = subprocess.call([sys.executable, *args], cwd=ROOT, env=env)
        if code:
            sys.exit(code)
