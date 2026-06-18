"""Event / schedule-based alert rules (observed-only).

missed_feeding and unexpected_feeding detect whether a *scheduled* feeding did or
did not happen. They are not threshold crossings over a forecastable metric, so
they stay observed-only. Logic moved verbatim from AlertMonitor; the engine passes
a `db`, an async `emit(alert_data)` sink, and the farm-local tzinfo.

(cancel_feeding_suggestion is forecast-based and is added in Phase 2.)
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

UTC = ZoneInfo("UTC")


def parse_time(value):
    """Coerce a schedule time field (time object or 'HH:MM[:SS]' string) to a time."""
    if value is None:
        return None
    if isinstance(value, str):
        for fmt in ("%H:%M:%S", "%H:%M"):
            try:
                return datetime.strptime(value, fmt).time()
            except ValueError:
                continue
        return None
    return value


def schedule_windows_local(schedule: dict, now_local: datetime):
    """Yield (start, end) localised feeding windows for a schedule.

    The window is the explicit [time_start, time_end] range the user set. A window
    whose end is at or before its start crosses midnight and ends the next day.

    Today's anchor is always considered. Yesterday's anchor is only considered for
    cross-midnight windows (whose end falls on today) — a same-day window belonging
    to yesterday was already evaluated on yesterday's runs, so re-emitting it would
    duplicate the alert once the cooldown expires.
    """
    days_of_week = schedule.get("days_of_week") or []
    time_start = parse_time(schedule.get("time_start"))
    time_end = parse_time(schedule.get("time_end"))
    if time_start is None or time_end is None:
        return

    crosses_midnight = time_end <= time_start
    tz = now_local.tzinfo
    offsets = (1, 0) if crosses_midnight else (0,)
    for offset in offsets:  # yesterday (cross-midnight only), then today
        anchor_date = (now_local - timedelta(days=offset)).date()
        if anchor_date.weekday() not in days_of_week:
            continue
        window_start = datetime.combine(anchor_date, time_start, tzinfo=tz)
        window_end = datetime.combine(anchor_date, time_end, tzinfo=tz)
        if crosses_midnight:
            window_end += timedelta(days=1)
        yield window_start, window_end


def upcoming_feeding_starts(schedule: dict, now_local: datetime, lookahead_hours: float):
    """Yield localized feeding start datetimes within (now, now + lookahead].

    Used by cancel_feeding_suggestion to find imminent scheduled feedings whose
    refill the forecast says would overfill the trough."""
    days_of_week = schedule.get("days_of_week") or []
    time_start = parse_time(schedule.get("time_start"))
    if time_start is None:
        return
    tz = now_local.tzinfo
    horizon = now_local + timedelta(hours=lookahead_hours)
    for offset in (0, 1):  # today, tomorrow
        anchor_date = (now_local + timedelta(days=offset)).date()
        if anchor_date.weekday() not in days_of_week:
            continue
        start = datetime.combine(anchor_date, time_start, tzinfo=tz)
        if now_local < start <= horizon:
            yield start


async def check_missed_feeding(
    db,
    emit,
    barn: dict,
    location: dict,
    schedules: list,
    feed_rise_percent: float,
    cooldown_hours: int,
    now_utc: datetime,
    local_tz,
):
    feeding_location_id = location.get("feeding_location_id")
    location_name = location.get("name")
    barn_id = barn.get("barn_id") or barn.get("id")
    now_local = now_utc.astimezone(local_tz)

    for schedule in schedules:
        if schedule.get("feeding_location_id") != feeding_location_id:
            continue
        if not schedule.get("is_active"):
            continue

        for window_start_local, window_end_local in schedule_windows_local(schedule, now_local):
            # Only judge a window once it has fully elapsed.
            if now_local < window_end_local:
                continue

            window_start = window_start_local.astimezone(UTC)
            window_end = window_end_local.astimezone(UTC)

            readings = db.get_feed_level_window(feeding_location_id, window_start, window_end)
            values = [r["numeric_value"] for r in readings if r.get("numeric_value") is not None]
            if not values:
                continue
            if max(values) - min(values) < feed_rise_percent:
                recent = db.get_recent_alert_for_location(
                    barn_id, "missed_feeding", feeding_location_id, cooldown_hours
                )
                if not recent:
                    await emit(
                        {
                            "alert_type": "missed_feeding",
                            "severity": "warning",
                            "barn_id": barn_id,
                            "barn_name": barn.get("name"),
                            "feeding_location_id": feeding_location_id,
                            "location_name": location_name,
                            "message": (
                                f"Scheduled feeding was missed at {location_name} "
                                f"(window {window_start_local.strftime('%Y-%m-%d %H:%M')}"
                                f"–{window_end_local.strftime('%H:%M')})."
                            ),
                        }
                    )


async def check_unexpected_feeding(
    db,
    emit,
    barn: dict,
    location: dict,
    schedules: list,
    feed_rise_percent: float,
    feed_rise_lookback_minutes: int,
    unexpected_cooldown_minutes: int,
    now_utc: datetime,
    local_tz,
):
    feeding_location_id = location.get("feeding_location_id")
    location_name = location.get("name")
    barn_id = barn.get("barn_id") or barn.get("id")
    now_local = now_utc.astimezone(local_tz)
    window_start = now_utc - timedelta(minutes=feed_rise_lookback_minutes)
    readings = db.get_feed_level_window(feeding_location_id, window_start, now_utc)
    values = [r["numeric_value"] for r in readings if r.get("numeric_value") is not None]
    if not values:
        return
    if max(values) - min(values) < feed_rise_percent:
        return

    # A rise is "expected" if now falls inside any active schedule's window.
    has_schedule = False
    for schedule in schedules:
        if schedule.get("feeding_location_id") != feeding_location_id:
            continue
        if not schedule.get("is_active"):
            continue
        for window_start_local, window_end_local in schedule_windows_local(schedule, now_local):
            if window_start_local <= now_local <= window_end_local:
                has_schedule = True
                break
        if has_schedule:
            break

    if has_schedule:
        return

    hours = unexpected_cooldown_minutes / 60.0
    recent = db.get_recent_alert_for_location(
        barn_id, "unexpected_feeding", feeding_location_id, hours
    )
    if recent:
        return

    await emit(
        {
            "alert_type": "unexpected_feeding",
            "severity": "info",
            "barn_id": barn_id,
            "barn_name": barn.get("name"),
            "feeding_location_id": feeding_location_id,
            "location_name": location_name,
            "message": f"Unexpected feeding detected at {location_name}.",
        }
    )
