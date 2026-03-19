from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable

from shapely.geometry import shape
from math import atan


def daterange(start: datetime, end: datetime) -> Iterable[datetime]:
    cur = start
    while cur <= end:
        yield cur
        cur = cur + timedelta(days=1)


def stull_wet_bulb(temp_c: float, rh: float) -> float:
    # Stull 2011 approximation
    tw = (
        temp_c * atan(0.151977 * (rh + 8.313659) ** 0.5)
        + atan(temp_c + rh)
        - atan(rh - 1.676331)
        + 0.00391838 * (rh ** 1.5) * atan(0.023101 * rh)
        - 4.686035
    )
    return float(tw)


def heat_index(temp_c: float, rh: float) -> float:
    # Convert to F for Rothfusz, then back to C.
    t_f = temp_c * 9 / 5 + 32
    if t_f < 80 or rh < 40:
        # simple formula
        hi_f = 0.5 * (t_f + 61.0 + ((t_f - 68.0) * 1.2) + (rh * 0.094))
    else:
        hi_f = (
            -42.379 + 2.04901523 * t_f + 10.14333127 * rh - 0.22475541 * t_f * rh
            - 6.83783e-3 * (t_f**2) - 5.481717e-2 * (rh**2)
            + 1.22874e-3 * (t_f**2) * rh + 8.5282e-4 * t_f * (rh**2)
            - 1.99e-6 * (t_f**2) * (rh**2)
        )
    return (hi_f - 32) * 5 / 9


def wbgt_approx(tw_c: float) -> float:
    # Very rough approximation: WBGT ~ 0.7*Tw + 0.2*Tshade + 0.1*Tglobe (assume Tshade~Tw, Tglobe~Tw)
    return float(0.7 * tw_c + 0.2 * tw_c + 0.1 * tw_c)
