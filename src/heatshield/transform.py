import pandas as pd
from heatshield.clean import clean_weather_data
from heatshield.heat_index import heat_index_f, celsius_to_fahrenheit

def generate_gold_layer(df):
    df = clean_weather_data(df)
    if 'temperature' in df.columns and 'humidity' in df.columns:
        temp_f = celsius_to_fahrenheit(df['temperature'].values)
        df['heat_index'] = heat_index_f(temp_f, df['humidity'].values)
    return df
