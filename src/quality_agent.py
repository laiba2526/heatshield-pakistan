import os
import json
import pandas as pd
from datetime import datetime

LOG_FILE = "logs/audit.jsonl"
QUARANTINE_DIR = "data/quarantine"

os.makedirs("logs", exist_ok=True)
os.makedirs(QUARANTINE_DIR, exist_ok=True)

def log_audit(record_id, check_name, action_taken, reason):
    entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "record_id": str(record_id),
        "check": check_name,
        "action": action_taken, # FIXED, FILLED, FLAGGED, QUARANTINED
        "reason": reason
    }
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")

def run_quality_checks(df_path: str) -> pd.DataFrame:
    print(f"[Data Quality Agent] Inspecting dataset at: {df_path}")
    if not os.path.exists(df_path):
        raise FileNotFoundError(f"Target dataset not found: {df_path}. Ensure ingestion or silver layer ran first.")

    df = pd.read_csv(df_path)
    clean_rows = []
    quarantine_rows = []

    for idx, row in df.iterrows():
        is_valid = True
        reasons = []

        # Check 1: Missing critical values
        if pd.isna(row.get('temperature_2m')) or pd.isna(row.get('relative_humidity_2m')):
            is_valid = False
            reasons.append("Missing essential temperature or humidity values.")
            log_audit(idx, "missing_values", "QUARANTINED", "Missing core weather metrics.")

        # Check 2: Physical bounds validation (-10°C to 60°C for Pakistan climate)
        elif not (-10 <= float(row['temperature_2m']) <= 60):
            is_valid = False
            reasons.append(f"Temperature {row['temperature_2m']}°C out of physical bounds.")
            log_audit(idx, "temp_bounds", "QUARANTINED", "Temperature reading out of valid range.")

        # Check 3: Relative Humidity bounds (0% to 100%)
        elif not (0 <= float(row['relative_humidity_2m']) <= 100):
            is_valid = False
            reasons.append(f"Humidity {row['relative_humidity_2m']}% out of bounds.")
            log_audit(idx, "humidity_bounds", "QUARANTINED", "Humidity out of range [0, 100].")

        if is_valid:
            clean_rows.append(row)
        else:
            quarantine_rows.append({**row.to_dict(), "quarantine_reasons": "; ".join(reasons)})

    df_clean = pd.DataFrame(clean_rows)
    
    if quarantine_rows:
        df_quarantine = pd.DataFrame(quarantine_rows)
        q_path = os.path.join(QUARANTINE_DIR, f"quarantined_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv")
        df_quarantine.to_csv(q_path, index=False)
        print(f"[Data Quality Agent] ⚠️ Quarantined {len(quarantine_rows)} invalid rows to {q_path}")
    else:
        print("[Data Quality Agent] ✅ All records passed quality gates successfully.")

    return df_clean

if __name__ == "__main__":
    target_file = "data/silver/weather_silver.csv"
    gold_dir = "data/gold"
    os.makedirs(gold_dir, exist_ok=True)
    
    if os.path.exists(target_file):
        cleaned_df = run_quality_checks(target_file)
        cleaned_df.to_csv(os.path.join(gold_dir, "weather_gold.csv"), index=False)
        print("[Data Quality Agent] Gold layer successfully updated with validated data.")
    else:
        print(f"[Warning] Silver layer file {target_file} not found. Running fallback generation for local testing.")
        # Fallback generation for testing if silver layer isn't generated yet
        from datetime import datetime, timedelta
        import numpy as np
        
        cities = ["Karachi", "Lahore", "Jacobabad", "Multan", "Peshawar"]
        sample_data = []
        for i in range(50):
            sample_data.append({
                "timestamp": (datetime.now() - timedelta(hours=i)).strftime("%Y-%m-%d %H:%M:%S"),
                "city": np.random.choice(cities),
                "temperature_2m": round(np.random.uniform(25, 48), 1),
                "relative_humidity_2m": round(np.random.uniform(30, 80), 1),
                "dew_point_2m": 22.5,
                "wind_speed_10m": 10.0,
                "heat_index": 42.0,
                "heat_risk_category": "Danger",
                "vulnerability_score": 0.75,
                "target_heat_index_t1": 43.0,
                "target_heat_index_t2": 44.0
            })
        fallback_df = pd.DataFrame(sample_data)
        os.makedirs("data/silver", exist_ok=True)
        fallback_df.to_csv(target_file, index=False)
        
        cleaned_df = run_quality_checks(target_file)
        cleaned_df.to_csv(os.path.join(gold_dir, "weather_gold.csv"), index=False)
        print("[Data Quality Agent] Fallback gold dataset created successfully.")
