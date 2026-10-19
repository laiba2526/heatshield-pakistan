import pandas as pd
from heatshield.heat_index import heat_index_f

def generate_gold_layer(df):
    """Apply heat index calculations to clean data to produce the Gold layer table."""
    df = df.copy()

    if 'temperature' in df.columns and 'humidity' in df.columns:
        # Calculate heat index using our vectorized function
        df['heat_index'] = heat_index_f(df['temperature'].values, df['humidity'].values)

    return df