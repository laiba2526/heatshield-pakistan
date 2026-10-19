import json
from pathlib import Path

manifest_path = Path("data/manifest.json")

with manifest_path.open("r", encoding="utf-8") as f:
    entries = json.load(f)

for entry in entries:
    source = entry.get("source", "")

    if source == "NASA POWER":
        # Correct the incorrect website placeholder.
        if entry.get("request_url") == "https://nasa.gov":
            entry["request_url"] = (
                "https://power.larc.nasa.gov/api/temporal/hourly/point"
            )

        entry["licence"] = (
            "Refer to NASA POWER official documentation and applicable "
            "data-use terms: https://power.larc.nasa.gov/docs/ "
            "Specific terms must be verified before redistribution."
        )

    elif source == "Official heatwave document":
        entry["licence"] = (
            "No open licence verified. Consult the original publisher's "
            "terms and use the document with appropriate attribution."
        )

with manifest_path.open("w", encoding="utf-8") as f:
    json.dump(entries, f, indent=2, ensure_ascii=False)
    f.write("\n")

print("Manifest metadata updated.")
print("Existing file paths and SHA-256 values were preserved.")