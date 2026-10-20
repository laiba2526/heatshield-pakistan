import numpy as np

from heatshield import config


def celsius_to_fahrenheit(temp_c):
    return temp_c * 9 / 5 + 32

def fahrenheit_to_celsius(temp_f):
    return (temp_f - 32) * 5 / 9

def heat_index_f(temp_f, rh_pct):
    """NWS heat index (Rothfusz regression with the official NWS adjustments).

    Below 80 F the air temperature is returned unchanged. Adjustments
    (NWS Technical Attachment SR 90-23 / WPC heat index equation):
      * RH < 13 % and 80 F <= T <= 112 F: subtract ((13-RH)/4) * sqrt((17-|T-95|)/17)
      * RH > 85 % and 80 F <= T <= 87 F:  add ((RH-85)/10) * ((87-T)/5)
    Missing values or RH outside 0..100 give NaN.
    """
    T = np.asarray(temp_f, dtype=float)
    RH = np.asarray(rh_pct, dtype=float)

    hi = np.full_like(T, np.nan)
    invalid = np.isnan(T) | np.isnan(RH) | (RH < 0) | (RH > 100)
    valid = ~invalid

    if not np.any(valid):
        return hi if np.ndim(temp_f) > 0 or np.ndim(rh_pct) > 0 else float('nan')

    T_v = T[valid]
    RH_v = RH[valid]
    result = np.empty_like(T_v)

    low_temp_mask = T_v < 80.0
    high_temp_mask = ~low_temp_mask

    result[low_temp_mask] = T_v[low_temp_mask]

    if np.any(high_temp_mask):
        Th = T_v[high_temp_mask]
        RHh = RH_v[high_temp_mask]

        c1 = -42.379
        c2 = 2.04901523
        c3 = 10.14333127
        c4 = -0.22475541
        c5 = -0.00683783
        c6 = -0.05481717
        c7 = 0.00122874
        c8 = 0.00085282
        c9 = -0.00000199

        rothfusz = (c1 + c2 * Th + c3 * RHh + c4 * Th * RHh + c5 * Th**2 + c6 * RHh**2 + c7 * Th**2 * RHh + c8 * Th * RHh**2 + c9 * Th**2 * RHh**2)

        dry = (RHh < 13) & (Th <= 112)
        rothfusz[dry] -= ((13 - RHh[dry]) / 4) * np.sqrt((17 - np.abs(Th[dry] - 95)) / 17)
        humid = (RHh > 85) & (Th <= 87)
        rothfusz[humid] += ((RHh[humid] - 85) / 10) * ((87 - Th[humid]) / 5)

        result[high_temp_mask] = rothfusz

    hi[valid] = result
    if np.ndim(temp_f) == 0 and np.ndim(rh_pct) == 0:
        return float(hi.item())
    return hi


def heat_index_c(temp_c, rh_pct):
    """Heat index in deg C from temperature in deg C and relative humidity in %."""
    return fahrenheit_to_celsius(heat_index_f(celsius_to_fahrenheit(np.asarray(temp_c, dtype=float)), rh_pct))


def risk_level(hi_c):
    """NWS risk category for a heat index in deg C (vectorised; NaN -> 'Unknown')."""
    hi = np.asarray(hi_c, dtype=float)
    labels = np.full(hi.shape, "Unknown", dtype=object)
    for name, lower, _ in config.RISK_LEVELS:
        labels[hi >= lower] = name
    if np.ndim(hi_c) == 0:
        return str(labels.item())
    return labels


def risk_color(level: str) -> str:
    return {name: color for name, _, color in config.RISK_LEVELS}.get(level, "#888888")

