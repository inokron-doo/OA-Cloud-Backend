"""Tests for forecast/observed timeline builders.

Run from the backend root: `python -m src.services.rules.test_forecast`
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.services.rules.forecast import (
    feed_timeline,
    nearest_level,
    thi_timeline,
    to_utc,
)

T0 = datetime(2026, 6, 18, 12, 0, tzinfo=timezone.utc)


def test_to_utc_variants():
    # naive datetime -> assumed UTC
    assert to_utc(datetime(2026, 6, 18, 12, 0)) == T0
    # aware datetime passes through
    assert to_utc(T0) == T0
    # ISO string with Z
    assert to_utc("2026-06-18T12:00:00Z") == T0
    # ISO string with offset -> converted to UTC
    assert to_utc("2026-06-18T14:00:00+02:00") == T0
    assert to_utc(None) is None
    assert to_utc("not-a-date") is None


def test_thi_timeline_from_forecast_rows():
    rows = [
        {"forecast_for": T0, "thi": 81.0, "temperature": 30.0, "humidity": 60},
        {"forecast_for": T0 + timedelta(hours=1), "thi": 82.0},  # no temperature
        {"forecast_for": None, "thi": 99.0},  # dropped (no time)
    ]
    ts = thi_timeline(rows, "forecast_for")
    assert len(ts) == 2
    assert ts[0].values["thi"] == 81.0 and ts[0].values["temp"] == 30.0
    assert "temp" not in ts[1].values  # no temperature key


def test_feed_timeline_merges_nearest_temp():
    weather = thi_timeline(
        [
            {"forecast_for": T0, "thi": 70, "temperature": 20.0},
            {"forecast_for": T0 + timedelta(hours=4), "thi": 78, "temperature": 28.0},
        ],
        "forecast_for",
    )
    forecast = [
        {"time": "2026-06-18T12:30:00Z", "level_percent": 80.0},  # nearest 12:00 -> 20C
        {"time": "2026-06-18T15:30:00Z", "level_percent": 78.0},  # nearest 16:00 -> 28C
    ]
    ts = feed_timeline(forecast, weather)
    assert ts[0].values["feed_level_pct"] == 80.0 and ts[0].values["temp"] == 20.0
    assert ts[1].values["temp"] == 28.0
    # without weather, no temp attached
    assert "temp" not in feed_timeline(forecast)[0].values


def test_feed_timeline_skips_bad_rows():
    forecast = [
        {"time": None, "level_percent": 50},
        {"time": "2026-06-18T12:00:00Z", "level_percent": None},
        {"time": "2026-06-18T13:00:00Z", "level_percent": 42.0},
    ]
    ts = feed_timeline(forecast)
    assert len(ts) == 1 and ts[0].values["feed_level_pct"] == 42.0


def test_nearest_level():
    ts = feed_timeline(
        [
            {"time": "2026-06-18T12:00:00Z", "level_percent": 90.0},
            {"time": "2026-06-18T16:00:00Z", "level_percent": 60.0},
        ]
    )
    assert nearest_level(ts, T0 + timedelta(hours=1)) == 90.0  # closer to 12:00
    assert nearest_level(ts, T0 + timedelta(hours=3)) == 60.0  # closer to 16:00


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print(f"  ok: {t.__name__}")
    print(f"\nAll {len(tests)} forecast tests passed.")


if __name__ == "__main__":
    _run_all()
