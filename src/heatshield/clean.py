import pandas as pd
from heatshield.quality import check_humidity_bounds

def clean_weather_data(df):
    """Clean raw weather data: handle missing values, duplicates, and invalid humidity."""
    # Remove exact duplicate rows
    df = df.drop_duplicates().copy()

    # Standardize column names (lowercase, strip whitespace)
    df.columns = [col.strip().lower() for col in df.columns]

    # Drop rows where essential temperature or humidity is missing
    if 'temperature' in df.columns and 'humidity' in df.columns:
        df = df.dropna(subset=['temperature', 'humidity'])

        # Filter out rows with impossible humidity values using our quality check
        valid_humidity = check_humidity_bounds(df['humidity'])
        df = df[valid_humidity]

    return df