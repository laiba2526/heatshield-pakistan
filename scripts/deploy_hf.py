"""Deploy (or update) the HeatShield dashboard as a Hugging Face Docker Space.

    pip install huggingface_hub
    set HF_TOKEN=hf_xxx            (a *write* token from https://huggingface.co/settings/tokens)
    python scripts/deploy_hf.py <hf-username>/heatshield-pakistan

``upload_folder`` handles binary files (parquet, joblib) through the Hub's
large-file storage, so no git-lfs setup is needed. The official NDMA / PDMA /
PMD PDFs and their extracted text are *not* uploaded - they are not openly
licensed - the Space downloads them from the publishers at start-up and checks
their SHA-256 against data/manifest.json.

No Space secrets are needed.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IGNORE = [
    ".git/*", ".venv/*", "**/__pycache__/*", ".pytest_cache/*",
    "data/_staging/*", "data/_archive/*", "data/bronze/documents/*.pdf", "data/rag/chunks.jsonl",
    "data/quarantine/*", "*.lock",
]


def main() -> int:
    if len(sys.argv) != 2 or "/" not in sys.argv[1]:
        print(__doc__)
        return 2
    try:
        from huggingface_hub import HfApi
    except ImportError:
        print("pip install huggingface_hub")
        return 2
    repo_id = sys.argv[1]
    api = HfApi(token=os.environ.get("HF_TOKEN"))
    api.create_repo(repo_id, repo_type="space", space_sdk="docker", exist_ok=True)
    api.upload_folder(folder_path=str(ROOT), repo_id=repo_id, repo_type="space",
                      ignore_patterns=IGNORE, commit_message="Deploy HeatShield dashboard")
    print(f"Deployed: https://huggingface.co/spaces/{repo_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
