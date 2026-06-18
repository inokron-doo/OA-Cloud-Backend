from typing import Any, Dict, Optional

from app.db import db

DEFAULT_PREDICTION_SETTINGS = {
    "prediction_history_hours": 168,
    "prediction_forecast_hours": 24,
    "prediction_resample_minutes": 15,
    "prediction_min_points": 30,
    "prediction_outlier_min_percent": 0,
    "prediction_outlier_max_percent": 100,
    "prediction_min_rate_percent_per_hour": 0.05,
    "prediction_max_rate_percent_per_hour": 8.0,
    "prediction_max_time_gap_hours": 2,
    "prediction_sudden_drop_percent": 15,
    "prediction_sudden_rise_percent": 15,
    "prediction_smoothing_window": 5,
    "prediction_refill_rise_percent": 3,
    "prediction_min_segment_points": 4,
    "prediction_day_start_hour": 6,
    "prediction_night_start_hour": 18,
    "prediction_timezone": "Europe/Ljubljana",
    "prediction_short_window_hours": 24,
    "prediction_medium_window_days": 7,
    "prediction_long_window_days": 30,
    "prediction_rate_blend_short_weight": 0.5,
    "prediction_rate_blend_medium_weight": 0.3,
    "prediction_rate_blend_long_weight": 0.2,
    "prediction_thi_enabled": True,
    "prediction_thi_mild_threshold": 68,
    "prediction_thi_high_threshold": 72,
    "prediction_thi_severe_threshold": 80,
    "prediction_thi_mild_rate_multiplier": 1.05,
    "prediction_thi_high_rate_multiplier": 1.15,
    "prediction_thi_severe_rate_multiplier": 1.3,
    "prediction_capacity_default_kg": 3000,
    "prediction_capacity_min_kg": 500,
    "prediction_capacity_max_kg": 15000,
    "prediction_capacity_estimation_enabled": True,
    "prediction_capacity_min_jump_percent": 5,
    "prediction_capacity_event_match_hours": 4,
    # NOTE: the prediction_thi_* keys above are consumption-rate multipliers (how
    # much feed intake slows in heat), NOT alert thresholds. Alerting moved to the
    # main backend's rule engine; the old prediction_low/high/within/lookahead keys
    # were removed with it.
}


def _apply_settings(target: Dict[str, Any], rows: list[Dict[str, Any]]) -> None:
    for row in rows:
        key = row.get("key")
        if not key:
            continue
        target[key] = row.get("value")


def resolve_prediction_settings(
    barn_id: Optional[str] = None,
    feeding_location_id: Optional[str] = None,
) -> Dict[str, Any]:
    db.create_prediction_settings_table()

    resolved = dict(DEFAULT_PREDICTION_SETTINGS)
    global_rows = db.get_prediction_settings("global", None)
    _apply_settings(resolved, global_rows)

    if barn_id:
        barn_rows = db.get_prediction_settings("barn", barn_id)
        _apply_settings(resolved, barn_rows)

    if feeding_location_id:
        location_rows = db.get_prediction_settings(
            "feeding_location", feeding_location_id
        )
        _apply_settings(resolved, location_rows)

    return resolved
