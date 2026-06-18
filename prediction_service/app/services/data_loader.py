from datetime import datetime, timedelta
from typing import Any, Dict, List

from app.db import db
from app.services.title_parser import parse_feeding_activity_title


def load_mapped_feeding_events_for_prediction(
    feeding_location_id: str,
    barn_id: str,
    history_hours: int,
    forecast_hours: int,
) -> Dict[str, List[Dict[str, Any]]]:
    now = datetime.utcnow()
    start_date = now - timedelta(hours=history_hours)
    end_date = now + timedelta(hours=forecast_hours)

    events: List[Dict[str, Any]] = []
    unmapped_events: List[Dict[str, Any]] = []

    activities = db.load_calendar_feeding_activities(barn_id, start_date, end_date)
    for activity in activities:
        parsed = parse_feeding_activity_title(activity.get("title"))
        source_key = parsed.get("source_location_key")
        if not source_key:
            unmapped_events.append(
                {
                    "activity": activity,
                    "reason": "title_parse_failed",
                }
            )
            continue

        location = db.get_feeding_location_by_source_key(barn_id, source_key)
        if not location:
            unmapped_events.append(
                {
                    "activity": activity,
                    "reason": "location_not_found",
                }
            )
            continue

        if str(location.get("feeding_location_id")) != feeding_location_id:
            unmapped_events.append(
                {
                    "activity": activity,
                    "reason": "location_mismatch",
                }
            )
            continue

        events.append(
            {
                "activity": activity,
                "parsed": parsed,
                "feeding_location": location,
            }
        )

    return {
        "events": events,
        "unmapped_events": unmapped_events,
    }


def load_prediction_input(
    feeding_location_id: str,
    history_hours: int,
    forecast_hours: int,
) -> Dict[str, Any]:
    feeding_location = db.get_feeding_location(feeding_location_id)
    if not feeding_location:
        raise ValueError("Feeding location not found")

    barn_id = feeding_location.get("barn_id")
    history = db.load_feed_history(feeding_location_id, history_hours)
    mapped = load_mapped_feeding_events_for_prediction(
        feeding_location_id, barn_id, history_hours, forecast_hours
    )

    return {
        "feeding_location": feeding_location,
        "history": history,
        "feeding_events": mapped["events"],
        "unmapped_events": mapped["unmapped_events"],
    }
