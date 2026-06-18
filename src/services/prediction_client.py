import os
from datetime import datetime

import httpx

PREDICTION_SERVICE_URL = os.getenv(
    "PREDICTION_SERVICE_URL",
    "http://127.0.0.1:8015",
).rstrip("/")

PREDICTION_SERVICE_API_KEY = os.getenv(
    "PREDICTION_SERVICE_API_KEY",
    "change-me",
)


async def get_feed_forecast_from_prediction_service(
    feeding_location_id: str,
    barn_id: str,
    history_hours: int | None = None,
    forecast_hours: int | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    apply_local_shift: bool = True,
):
    payload = {
        "feeding_location_id": feeding_location_id,
        "barn_id": barn_id,
    }

    if history_hours:
        payload["history_hours"] = history_hours

    if forecast_hours:
        payload["forecast_hours"] = forecast_hours

    if start_time:
        payload["start_time"] = start_time.isoformat()

    if end_time:
        payload["end_time"] = end_time.isoformat()

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            f"{PREDICTION_SERVICE_URL}/api/v1/predict/feed-level",
            json=payload,
            headers={
                "X-Prediction-API-Key": PREDICTION_SERVICE_API_KEY,
            },
        )

    response.raise_for_status()
    data = response.json()

    # The alert engine needs raw UTC timestamps for predicted_for / horizon math,
    # so it calls with apply_local_shift=False. The legacy chart endpoint keeps the
    # fake-local shift for now (the frontend rewrite will localize at the edge).
    if not apply_local_shift:
        return data

    # Shift timezone for frontend (simulate local time but serialized as UTC)
    if "result" in data and isinstance(data["result"], dict):
        try:
            from zoneinfo import ZoneInfo
            from datetime import timezone
            ljubljana = ZoneInfo("Europe/Ljubljana")
            
            # Shift the main current_time
            curr_time = data["result"].get("current_time")
            if curr_time:
                try:
                    dt = datetime.fromisoformat(curr_time)
                    dt_fake_utc = dt.astimezone(ljubljana).replace(tzinfo=timezone.utc)
                    data["result"]["current_time"] = dt_fake_utc.isoformat()
                except ValueError:
                    pass

            # Shift the forecast list timestamps
            forecast = data["result"].get("forecast", [])
            for item in forecast:
                ts_str = item.get("time")
                if ts_str:
                    try:
                        dt = datetime.fromisoformat(ts_str)
                        dt_fake_utc = dt.astimezone(ljubljana).replace(tzinfo=timezone.utc)
                        item["time"] = dt_fake_utc.isoformat()
                    except ValueError:
                        pass
                        
            # Shift the applied_refills timestamps
            refills = data["result"].get("applied_refills", [])
            for item in refills:
                ts_str = item.get("time")
                if ts_str:
                    try:
                        dt = datetime.fromisoformat(ts_str)
                        dt_fake_utc = dt.astimezone(ljubljana).replace(tzinfo=timezone.utc)
                        item["time"] = dt_fake_utc.isoformat()
                    except ValueError:
                        pass
        except Exception as e:
            pass
            
    return data
