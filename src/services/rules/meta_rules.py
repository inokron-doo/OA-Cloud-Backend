"""Meta / correlation alert rules (observed-only).

health_spike: a single rate-based MooHero alert that replaces the old per-event
`animal_health` alert plus the two overlapping `health_spike_weather` /
`health_spike_feeding` alerts. Fire when >= spike_count HealthProblemEvents occur
within spike_hours at a scope, evaluated at BOTH barn and feeding-location scope
independently, then attribute a suspected cause (heat / feeding / unexplained) as
a field on the one alert.
"""

from __future__ import annotations

from src.services.rules import health

FEED_ALERT_TYPES = [
    "low_feed",
    "low_feed_recurring",
    "spoilage_risk",
    "missed_feeding",
    "unexpected_feeding",
]


def _as_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value, default):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _heat_coincidence(db, barn_id: str, spike_hours: int, thi_window_hours: int, thi_delta: float) -> bool:
    """Barn-level heat coincidence: an active heat_stress alert, or a current THI
    that deviates from the recent average by at least thi_delta."""
    heat_alert_active = db.get_recent_alerts(barn_id, "heat_stress", spike_hours) is not None
    current_weather = db.get_weather_data_for_barn(barn_id) or {}
    current_thi = current_weather.get("thi")
    history = db.get_weather_history(barn_id, thi_window_hours) or []
    thi_values = [h.get("thi") for h in history if h.get("thi") is not None]
    avg_thi = (sum(thi_values) / len(thi_values)) if thi_values else None
    return health.has_heat_coincidence(current_thi, avg_thi, thi_delta, heat_alert_active)


def _feeding_coincidence(db, feeding_location_id: str, feed_alert_hours: int) -> bool:
    if not feeding_location_id:
        return False
    return bool(
        db.get_recent_alerts_for_location_by_types(
            feeding_location_id, FEED_ALERT_TYPES, feed_alert_hours
        )
    )


async def check_health_spike(db, emit, barn: dict, locations: list, now_utc=None):
    """Evaluate health_spike at barn scope and at each location scope independently."""
    barn_id = barn.get("barn_id") or barn.get("id")
    if not barn_id:
        return

    spike_count = _as_int(db.get_threshold_value("health_spike_count", default=3), 3)
    spike_hours = _as_int(db.get_threshold_value("health_spike_hours", default=24), 24)
    thi_window_hours = _as_int(db.get_threshold_value("health_spike_thi_window_hours", default=24), 24)
    thi_delta = _as_float(db.get_threshold_value("health_spike_thi_delta", default=8), 8)
    feed_alert_hours = _as_int(db.get_threshold_value("health_spike_feed_alert_hours", default=12), 12)
    cooldown_hours = _as_int(db.get_threshold_value("moohero_alert_cooldown_hours", default=6), 6)

    has_heat = _heat_coincidence(db, barn_id, spike_hours, thi_window_hours, thi_delta)

    # --- Barn scope ---
    barn_events = db.get_recent_health_events_by_barn(barn_id, spike_hours)
    if health.is_spike(len(barn_events), spike_count):
        recent = db.get_recent_barn_scope_alert(barn_id, "health_spike", cooldown_hours)
        if not recent:
            # Barn-level feeding coincidence: any location in the barn with a recent feed alert.
            has_feeding = any(
                _feeding_coincidence(db, loc.get("feeding_location_id"), feed_alert_hours)
                for loc in locations
            )
            causes = health.attribute_cause(has_heat, has_feeding)
            await emit(
                {
                    "alert_type": "health_spike",
                    "severity": "warning",
                    "barn_id": barn_id,
                    "barn_name": barn.get("name"),
                    "feeding_location_id": None,
                    "location_name": None,
                    "scope": "barn",
                    "event_count": len(barn_events),
                    "window_hours": spike_hours,
                    "suspected_cause": causes,
                    "message": health.spike_message(
                        len(barn_events), spike_hours, barn.get("name") or "barn", causes
                    ),
                }
            )

    # --- Location scope ---
    for location in locations:
        feeding_location_id = location.get("feeding_location_id")
        if not feeding_location_id:
            continue
        loc_events = db.get_recent_health_events_by_location(feeding_location_id, spike_hours)
        if not health.is_spike(len(loc_events), spike_count):
            continue
        recent = db.get_recent_alert_for_location(
            barn_id, "health_spike", feeding_location_id, cooldown_hours
        )
        if recent:
            continue
        has_feeding = _feeding_coincidence(db, feeding_location_id, feed_alert_hours)
        causes = health.attribute_cause(has_heat, has_feeding)
        location_name = location.get("name")
        await emit(
            {
                "alert_type": "health_spike",
                "severity": "warning",
                "barn_id": barn_id,
                "barn_name": barn.get("name"),
                "feeding_location_id": feeding_location_id,
                "location_name": location_name,
                "scope": "location",
                "event_count": len(loc_events),
                "window_hours": spike_hours,
                "suspected_cause": causes,
                "message": health.spike_message(
                    len(loc_events), spike_hours, location_name or "location", causes
                ),
            }
        )
