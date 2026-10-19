import numpy as np
from heatshield.heat_index import (
    celsius_to_fahrenheit, fahrenheit_to_celsius, heat_index_f
)

def test_conversion_round_trip():
    assert abs(fahrenheit_to_celsius(celsius_to_fahrenheit(37.5)) - 37.5) < 1e-9

def test_known_value_at_80F_40pct():
    assert abs(heat_index_f(80, 40) - 79.93) < 0.05

def test_known_value_at_90F_60pct():
    assert abs(heat_index_f(90, 60) - 100) < 1.0

def test_more_humidity_means_hotter():
    assert heat_index_f(95, 40) < heat_index_f(95, 60) < heat_index_f(95, 80)

def test_missing_input_gives_nan():
    assert np.isnan(heat_index_f(np.nan, 50))

def test_impossible_humidity_gives_nan():
    assert np.isnan(heat_index_f(90, 120))