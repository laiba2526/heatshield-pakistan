import pandas as pd

def calculate_historical_baseline(df):
    baseline = {}
    if 'temperature' in df.columns:
        baseline['mean_temperature'] = df['temperature'].mean()
    if 'humidity' in df.columns:
        baseline['mean_humidity'] = df['humidity'].mean()
    return baseline
