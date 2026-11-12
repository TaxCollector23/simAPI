"""Learn conservative screening limits from reference episodes.

Suggestions describe observed inliers, not manufacturer-rated robot limits.
Extremes more than one percentile span beyond the robust range are counted as
contamination. The margin pads each end of the robust span; retained
observations are always enclosed unless a physical cap wins.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from core.robotics_trajectory import normalize
from integrations.robotics_validation import validate_robotics_frame

_CAPS = {"torque": 150.0, "velocity": 3.0, "acceleration": 25.0, "position": 2 * math.pi}


def suggest_limits(clean_rows, margin=1.25):
    """Return API-format ``robotics_limits`` plus warnings for unusable signals."""
    if isinstance(margin, bool) or not isinstance(margin, (int, float)) or not math.isfinite(margin) or margin < 1:
        raise ValueError("margin must be a finite number greater than or equal to 1")
    frame = pd.DataFrame(clean_rows)
    if frame.empty:
        raise ValueError("clean_rows must contain usable reference samples")
    limits, warnings = {}, []
    for column in frame:
        signal = normalize(str(column))
        cap = next((cap for suffix, cap in _CAPS.items() if signal.endswith("_" + suffix)), None)
        if cap is None:
            continue
        values = pd.to_numeric(frame[column], errors="coerce").to_numpy(dtype=float)
        values = values[np.isfinite(values)]
        if not len(values):
            warnings.append(f"{signal}: no usable reference samples")
            continue
        lo, hi = np.percentile(values, [1, 99])
        width = hi - lo
        if width <= 1e-12:
            warnings.append(f"{signal}: frozen signal; no limit suggested")
            continue
        retained = values[(values >= lo - width) & (values <= hi + width)]
        contamination = len(values) - len(retained)
        if contamination:
            warnings.append(f"{signal}: {contamination} contamination sample(s) ignored")
        pad = (margin - 1) * width
        low = max(-cap, min(float(retained.min()), lo - pad))
        high = min(cap, max(float(retained.max()), hi + pad))
        if low >= high:
            warnings.append(f"{signal}: reference samples outside physical caps; no limit suggested")
            continue
        limits[signal] = [float(low), float(high)]
    if not limits and not warnings:
        raise ValueError("clean_rows contain no usable robotics signals")
    return {"robotics_limits": limits, "warnings": warnings}


def suggest_and_validate(clean_rows, new_rows, margin=1.25):
    """Learn from reference samples, then validate new samples with those limits."""
    suggestion = suggest_limits(clean_rows, margin)
    if not suggestion["robotics_limits"]:
        raise ValueError("clean_rows produced no usable limits")
    frame = pd.DataFrame(new_rows)
    if frame.empty:
        raise ValueError("new_rows must contain samples")
    report = validate_robotics_frame(frame, limits=suggestion["robotics_limits"])
    return {**suggestion, "validation": report}
