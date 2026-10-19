import json
from pathlib import Path

MANIFEST = Path("data/manifest.json")
items = json.loads(MANIFEST.read_text())

for item in items:
    # Fill the publisher for official documents, based on the file name
    if str(item.get("publisher", "")).startswith("FILL"):
        title = item.get("title", "").lower()
        if title.startswith("ndma"):
            item["publisher"] = "National Disaster Management Authority (NDMA), Pakistan"
        elif title.startswith("pdma"):
            item["publisher"] = "Provincial Disaster Management Authority (PDMA), Sindh"

    # Point licence blanks to your sources.md, where the real wording lives
    if str(item.get("licence", "")).startswith("FILL"):
        item["licence"] = "See docs/sources.md (licence and terms checked by Member 1)"

MANIFEST.write_text(json.dumps(items, indent=2))

power = list(Path("data/bronze/nasa_power").glob("*.json"))
pdfs = list(Path("data/bronze/documents").glob("*.pdf"))
left = [i for i in items if "FILL" in json.dumps(i)]

print("NASA POWER files:", len(power), "(expected 15)")
print("PDF documents:  ", len(pdfs), "(expected 3)")
print("Manifest entries:", len(items))
print("Entries still with FILL:", len(left))