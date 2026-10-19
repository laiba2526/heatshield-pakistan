import pandas as pd

def clean_weather_data(df):
    df = df.copy()
    df.columns = df.columns.str.strip().str.lower()
    column_mapping = {'t2m': 'temperature', 'rh2m': 'humidity', 't2mdew': 'dew_point', 'ws10m': 'wind_speed', 'temperature_2m': 'temperature', 'relative_humidity_2m': 'humidity', 'relativehumidity_2m': 'humidity'}
    df = df.rename(columns=column_mapping)
    return df
