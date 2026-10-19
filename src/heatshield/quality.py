import pandas as pd
import numpy as np

def check_missing_values(df):
    """Return count of missing values per column."""
    return df.isnull().sum()

def check_duplicates(df):
    """Return count of duplicate rows."""
    return df.duplicated().sum()

def check_humidity_bounds(rh_series):
    """Check if relative humidity values fall between 0 and 100."""
    return (rh_series >= 0) & (rh_series <= 100)