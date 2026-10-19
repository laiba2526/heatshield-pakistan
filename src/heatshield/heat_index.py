import numpy as np

def celsius_to_fahrenheit(temp_c):
    return temp_c * 9 / 5 + 32

def fahrenheit_to_celsius(temp_f):
    return (temp_f - 32) * 5 / 9

def heat_index_f(temp_f, rh_pct):
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
        result[high_temp_mask] = rothfusz
        
    hi[valid] = result
    if np.ndim(temp_f) == 0 and np.ndim(rh_pct) == 0:
        return float(hi.item())
    return hi
