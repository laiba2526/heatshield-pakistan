import pathlib

transform_code = '''import pandas as pd
from heatshield.clean import clean_weather_data
from heatshield.heat_index import heat_index_f, celsius_to_fahrenheit

def generate_gold_layer(df):
    df = clean_weather_data(df)
    if 'temperature' in df.columns and 'humidity' in df.columns:
        temp_f = celsius_to_fahrenheit(df['temperature'].values)
        df['heat_index'] = heat_index_f(temp_f, df['humidity'].values)
    return df
'''

baseline_code = '''import pandas as pd

def calculate_historical_baseline(df):
    baseline = {}
    if 'temperature' in df.columns:
        baseline['mean_temperature'] = df['temperature'].mean()
    if 'humidity' in df.columns:
        baseline['mean_humidity'] = df['humidity'].mean()
    return baseline
'''

pathlib.Path('src/heatshield/transform.py').write_text(transform_code, encoding='utf-8')
pathlib.Path('src/heatshield/baseline.py').write_text(baseline_code, encoding='utf-8')
print('Successfully updated transform.py and baseline.py!')
