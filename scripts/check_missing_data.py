
import json
import glob
import os

files = glob.glob("data/bronze/nasa_power/*.json")
files += glob.glob("data/bronze/open_meteo/archive*.json")

print("\n===== MEMBER 1: MISSING DATA REPORT =====\n")

for file in files:
    print(f"\nFile: {os.path.basename(file)}")

    try:
        with open(file, "r", encoding="utf-8") as f:
            data = json.load(f)

        def inspect(obj, path=""):
            if isinstance(obj, dict):
                for key, value in obj.items():
                    inspect(value, f"{path}.{key}" if path else key)

            elif isinstance(obj, list):
                if obj and all(not isinstance(x, (dict, list)) for x in obj):
                    missing = sum(
                        x is None or
                        (isinstance(x, str) and (
                            x.strip() == "" or
                            x.strip() in ("-999", "-999.0", "NaN")
                        ))
                        for x in obj
                    )

                    if missing:
                        print(f"  {path}: {missing}/{len(obj)} missing values")

        inspect(data)

        # Check hourly timestamp gaps in Open-Meteo archive data
        if "open_meteo" in file.replace("\\", "/"):
            hourly = data.get("hourly", {})
            times = hourly.get("time", [])

            if times:
                import datetime

                parsed = []
                for t in times:
                    try:
                        parsed.append(datetime.datetime.fromisoformat(t))
                    except (ValueError, TypeError):
                        pass

                parsed = sorted(set(parsed))
                gaps = sum(
                    int((b - a).total_seconds() / 3600) - 1
                    for a, b in zip(parsed, parsed[1:])
                    if (b - a).total_seconds() > 3600
                )

                print(f"  Timestamp count: {len(times)}")
                print(f"  Missing hourly timestamps inside range: {gaps}")

        print("  Inspection complete.")

    except Exception as e:
        print(f"  ERROR: {e}")

print("\n===== REPORT FINISHED =====")

# Additional NASA POWER fill-value check
print("\n===== NASA POWER FILL-VALUE CHECK =====")

for file in glob.glob("data/bronze/nasa_power/*.json"):
    try:
        with open(file, "r", encoding="utf-8") as f:
            data = json.load(f)

        parameters = data.get("properties", {}).get("parameter", {})
        found = False

        for parameter, values in parameters.items():
            if isinstance(values, dict):
                fill_count = sum(
                    str(value).strip() in ("-999", "-999.0")
                    for value in values.values()
                )

                if fill_count:
                    print(
                        f"{os.path.basename(file)} | "
                        f"{parameter}: {fill_count} fill values"
                    )
                    found = True

        if not found:
            print(f"{os.path.basename(file)}: no -999 values detected")

    except Exception as e:
        print(f"{os.path.basename(file)}: ERROR - {e}")
