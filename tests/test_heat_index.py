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

# --- added: NWS adjustments, Celsius helper, risk levels -------------------
from heatshield.heat_index import heat_index_c, risk_level


def test_low_humidity_adjustment_lowers_index():
    # Hand calculation: Rothfusz(100 F, 5 %) = 94.18 F; adjustment ((13-5)/4)*sqrt((17-5)/17) = 1.68
    assert abs(heat_index_f(100, 5) - (94.18 - 1.68)) < 0.02


def test_high_humidity_adjustment_raises_index():
    # Hand calculation: Rothfusz(84 F, 95 %) = 100.28 F; adjustment ((95-85)/10)*((87-84)/5) = 0.60
    assert abs(heat_index_f(84, 95) - (100.28 + 0.60)) < 0.02


def test_celsius_wrapper():
    assert abs(heat_index_c(32.2, 60) - fahrenheit_to_celsius(heat_index_f(celsius_to_fahrenheit(32.2), 60))) < 1e-9


def test_risk_levels():
    assert list(risk_level(np.array([20, 27, 33, 40, 52, np.nan]))) == \
        ["Low", "Caution", "Extreme Caution", "Danger", "Extreme Danger", "Unknown"]
