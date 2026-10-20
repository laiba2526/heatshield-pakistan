"""Deploy (or update) the HeatShield dashboard on Hugging Face Spaces.

    pip install huggingface_hub
    hf auth login                                    (once; or set HF_TOKEN, a *write* token)
    python scripts/deploy_hf.py <hf-username>/heatshield-pakistan

Default: a free **static** Space. ``scripts/build_static_space.py`` packs the app
and the latest trusted data; the dashboard runs in the browser via stlite and
GitHub Actions refreshes the data hourly (``.github/workflows/hourly-refresh.yml``).

``--docker``: a Docker Space running the full app with its own hourly refresher
(``Dockerfile``). Hugging Face requires a PRO subscription for Docker Spaces.
The official NDMA / PDMA / PMD PDFs are not uploaded in either mode; the
Docker Space downloads them from the publishers and checks their SHA-256.

No Space secrets are needed.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCKER_IGNORE = [
    ".git/*", ".venv/*", "**/__pycache__/*", ".pytest_cache/*", "build/*",
    "data/_staging/*", "data/_archive/*", "data/bronze/documents/*.pdf", "data/rag/chunks.jsonl",
    "data/quarantine/*", "*.lock",
]


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    docker = "--docker" in sys.argv
    if len(args) != 1 or "/" not in args[0]:
        print(__doc__)
        return 2
    try:
        from huggingface_hub import HfApi
    except ImportError:
        print("pip install huggingface_hub")
        return 2
    repo_id = args[0]
    api = HfApi(token=os.environ.get("HF_TOKEN") or None)
    if docker:
        api.create_repo(repo_id, repo_type="space", space_sdk="docker", exist_ok=True)
        api.upload_folder(folder_path=str(ROOT), repo_id=repo_id, repo_type="space",
                          ignore_patterns=DOCKER_IGNORE, commit_message="Deploy HeatShield dashboard (Docker)")
    else:
        sys.path.insert(0, str(ROOT / "scripts"))
        from build_static_space import build
        site = build()
        api.create_repo(repo_id, repo_type="space", space_sdk="static", exist_ok=True)
        api.upload_folder(folder_path=str(site), repo_id=repo_id, repo_type="space",
                          commit_message="Update HeatShield dashboard and trusted data")
    print(f"Deployed: https://huggingface.co/spaces/{repo_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
