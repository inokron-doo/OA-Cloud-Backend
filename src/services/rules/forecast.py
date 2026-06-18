"""Forecast/observed timeline builders for the continuous rule evaluator.

Turn raw DB/forecast-service rows into `Sample` timelines (tz-aware UTC). Kept
free of DB/network calls so the parsing + temp-merge logic is unit-testable; the
engine fetches the rows and passes them in.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from src.services.rules.continuous import Sample


def to_utc(value) -> Optional[datetime]:
    """Coerce a datetime or ISO-8601 string to an aware UTC datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def thi_timeline(rows: list, time_key: str) -> list[Sample]:
    """Build a THI timeline from weather rows (observed: obs_time; forecast: forecast_for).

    Each sample carries `thi` and, when present, `temp` (for spoilage's gate)."""
    out: list[Sample] = []
    for r in rows:
        t = to_utc(r.get(time_key))
        if t is None:
            continue
        values = {}
        if r.get("thi") is not None:
            values["thi"] = float(r["thi"])
        if r.get("temperature") is not None:
            values["temp"] = float(r["temperature"])
        if values:
            out.append(Sample(t=t, values=values))
    return out


def _nearest_value(t: datetime, samples: list[Sample], key: str) -> Optional[float]:
    best = None
    best_diff = None
    for s in samples:
        if key not in s.values:
            continue
        diff = abs((s.t - t).total_seconds())
        if best_diff is None or diff < best_diff:
            best_diff = diff
            best = s.values[key]
    return best


def feed_timeline(forecast_list: list, weather_samples: Optional[list] = None) -> list[Sample]:
    """Build a feed-level timeline from the prediction service forecast
    ([{time, level_percent}, ...]). When weather_samples are given, the nearest
    forecast temperature is attached as `temp` so the spoilage temp-gate can run
    on predicted samples."""
    out: list[Sample] = []
    for item in forecast_list or []:
        t = to_utc(item.get("time"))
        level = item.get("level_percent")
        if t is None or level is None:
            continue
        values = {"feed_level_pct": float(level)}
        if weather_samples:
            temp = _nearest_value(t, weather_samples, "temp")
            if temp is not None:
                values["temp"] = temp
        out.append(Sample(t=t, values=values))
    return out


def nearest_level(forecast_samples: list[Sample], t: datetime) -> Optional[float]:
    """Predicted feed level closest in time to t (for cancel_feeding_suggestion)."""
    return _nearest_value(t, forecast_samples, "feed_level_pct")
