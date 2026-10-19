import sys
import os
import glob
import json
import pandas as pd

# Add 'src' directory to Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), 'src')))

from heatshield.quality import check_missing_values
from heatshield.clean import clean_weather_data
from heatshield.transform import generate_gold_layer

def parse_nasa_power_json(file_path):
    """Extracts time-series parameters from NASA POWER JSON structure into a clean DataFrame."""
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # NASA POWER format usually stores parameters under properties -> parameter
    try:
        parameters = data.get('properties', {}).get('parameter', {})
        if not parameters:
            raise ValueError("Could not find 'properties.parameter' in NASA JSON structure.")
        
        # Convert the dictionary of parameters (each is a dict of date:value) into a DataFrame
        df = pd.DataFrame(parameters)
        df.index.name = 'date'
        df.reset_index(inplace=True)
        return df
    except Exception as e:
        # Fallback to direct dataframe normalization if structure differs
        print(f"Notice: Using fallback JSON parser ({e})")
        return pd.json_normalize(data)

def run_integration_test():
    print("--- Starting HeatShield Pipeline Integration Test (NASA POWER Parser) ---")
    
    search_path = "data/bronze/nasa_power/*.json"
    files = glob.glob(search_path)
    
    if not files:
        print("⚠️ No NASA POWER JSON files found.")
        return

    bronze_file_path = files[0]
    
    try:
        # 1. Parse the raw nested JSON into a proper tabular DataFrame
        df = parse_nasa_power_json(bronze_file_path)
        print(f"✅ Successfully parsed NASA POWER file: {bronze_file_path}")
        print(f"✅ Tabular DataFrame Shape: {df.shape}")
        print("Columns extracted:", df.columns.tolist()[:6], "...")

        # 2. Run quality checks
        missing_report = check_missing_values(df)
        print("✅ Quality check executed successfully.")

        # 3. Run cleaning pipeline
        cleaned_df = clean_weather_data(df)
        print("✅ Cleaning pipeline executed successfully.")

        # 4. Run gold transformation (calculates heat indices)
        gold_df = generate_gold_layer(cleaned_df)
        print("✅ Gold transformation executed successfully! Heat indices generated.")
        print("Sample Gold Output Rows:\n", gold_df.head(2))

    except Exception as e:
        print("\n⚠️ PIPELINE INTEGRATION ERROR:")
        print("Error details:", e)

if __name__ == "__main__":
    run_integration_test()