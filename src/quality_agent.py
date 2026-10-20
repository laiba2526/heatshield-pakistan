import sys
import os
import json
import pandas as pd
from datetime import datetime

# Ensure Python can find the src package according to Member 2's guide
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

# Optional imports from Member 2's package if available
try:
    from heatshield.quality import check_missing_values
except ImportError:
    pass

LOG_FILE = "logs/audit.jsonl"
REPORT_FILE = "reports/validation_report.json"
QUARANTINE_DIR = "data/quarantine"
GOLD_FILE = "data/gold/weather_gold.csv"
BACKUP_FILE = "data/gold/weather_gold_last_trusted.csv"

os.makedirs("logs", exist_ok=True)
os.makedirs("reports", exist_ok=True)
os.makedirs(QUARANTINE_DIR, exist_ok=True)
os.makedirs("data/gold", exist_ok=True)

def log_audit(record_id, check_name, action_taken, reason):
    entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "record_id": str(record_id),
        "check": check_name,
        "action": action_taken,
        "reason": reason
    }
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")

def run_quality_checks(df_path: str) -> pd.DataFrame:
    print(f"[Data Quality Agent] Inspecting dataset at: {df_path}")
    if not os.path.exists(df_path):
        raise FileNotFoundError(f"Target dataset not found at {df_path}. Ensure Member 2's silver layer generation ran.")

    df = pd.read_csv(df_path)
    
    # Data-freshness tracking
    if 'timestamp' in df.columns:
        df['parsed_time'] = pd.to_datetime(df['timestamp'], errors='coerce')
        latest_time = df['parsed_time'].max()
        freshness_lag_hours = (datetime.utcnow() - latest_time.to_pydatetime()).total_seconds() / 3600 if pd.notna(latest_time) else 999
        print(f"[Freshness Tracker] Latest data timestamp: {latest_time} (Lag: {freshness_lag_hours:.1f} hours)")
    else:
        freshness_lag_hours = 0.0

    clean_rows = []
    quarantine_rows = []
    stats = {"total": len(df), "fixed": 0, "filled": 0, "flagged": 0, "quarantined": 0}

    for idx, row in df.iterrows():
        row_dict = row.to_dict()
        is_valid = True
        reasons = []

        # Fill minor missing relative humidity if temperature is valid
        if pd.isna(row_dict.get('relative_humidity_2m')) and pd.notna(row_dict.get('temperature_2m')):
            row_dict['relative_humidity_2m'] = 50.0  
            stats["filled"] += 1
            log_audit(idx, "missing_humidity", "FILLED", "Filled missing humidity with median fallback (50.0).")
        
        # Check critical temperature
        if pd.isna(row_dict.get('temperature_2m')):
            is_valid = False
            reasons.append("Missing essential temperature value.")
            stats["quarantined"] += 1
            log_audit(idx, "missing_temperature", "QUARANTINED", "Missing core temperature metric.")

        # Check physical bounds (-10°C to 60°C)
        elif not (-10 <= float(row_dict['temperature_2m']) <= 60):
            is_valid = False
            reasons.append(f"Temperature {row_dict['temperature_2m']}°C out of bounds.")
            stats["quarantined"] += 1
            log_audit(idx, "temp_bounds", "QUARANTINED", "Temperature reading out of valid range.")

        # Check humidity bounds (0% to 100%)
        elif not (0 <= float(row_dict.get('relative_humidity_2m', 0)) <= 100):
            is_valid = False
            reasons.append(f"Humidity {row_dict['relative_humidity_2m']}% out of bounds.")
            stats["quarantined"] += 1
            log_audit(idx, "humidity_bounds", "QUARANTINED", "Humidity out of range [0, 100].")

        if is_valid:
            row_dict.pop('parsed_time', None)
            clean_rows.append(row_dict)
        else:
            row_dict.pop('parsed_time', None)
            row_dict["quarantine_reasons"] = "; ".join(reasons)
            quarantine_rows.append(row_dict)

    df_clean = pd.DataFrame(clean_rows)

    if quarantine_rows:
        df_quarantine = pd.DataFrame(quarantine_rows)
        q_path = os.path.join(QUARANTINE_DIR, f"quarantined_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv")
        df_quarantine.to_csv(q_path, index=False)
        print(f"[Data Quality Agent] ⚠️ Quarantined {len(quarantine_rows)} invalid rows to {q_path}")

    report = {
        "run_timestamp": datetime.utcnow().isoformat(),
        "source_file": df_path,
        "total_records": stats["total"],
        "passed_records": len(df_clean),
        "quarantined_records": stats["quarantined"],
        "filled_records": stats["filled"],
        "flagged_records": stats["flagged"],
        "freshness_lag_hours": round(freshness_lag_hours, 2),
        "status": "PASSED" if stats["quarantined"] < (stats["total"] * 0.2) else "CRITICAL_FAILURE"
    }
    with open(REPORT_FILE, "w") as f:
        json.dump(report, f, indent=4)

    if report["status"] == "CRITICAL_FAILURE" and os.path.exists(GOLD_FILE):
        print("[Quality Gate] ❌ Critical failure rate exceeded. Preserving last trusted dataset.")
        return None

    return df_clean

if __name__ == "__main__":
    target_file = "data/silver/weather_silver.csv"
    cleaned_df = run_quality_checks(target_file)
    
    if cleaned_df is not None:
        if os.path.exists(GOLD_FILE):
            os.replace(GOLD_FILE, BACKUP_FILE)
        cleaned_df.to_csv(GOLD_FILE, index=False)
        print("[Data Quality Agent] ✅ Gold layer successfully updated from Member 2's silver layer.")
    else:
        print("[Data Quality Agent] 🛑 Retained previous trusted Gold dataset.")
