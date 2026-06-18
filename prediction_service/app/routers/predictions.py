from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, status

from app.schemas.prediction import FeedForecastRequest, FeedForecastResponse
from app.security import get_internal_api_key
from app.services.data_loader import load_prediction_input
from app.services.forecast_engine import generate_feed_forecast
from app.services.settings_service import resolve_prediction_settings

router = APIRouter()


def _verify_api_key(api_key: Optional[str]) -> None:
    expected = get_internal_api_key()
    if not expected:
        return
    if api_key != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")


@router.post("/api/v1/predict/feed-level", response_model=FeedForecastResponse)
def feed_forecast(
    payload: FeedForecastRequest,
    api_key: Optional[str] = Header(default=None, alias="X-Prediction-API-Key"),
) -> FeedForecastResponse:
    _verify_api_key(api_key)

    settings = resolve_prediction_settings(
        barn_id=payload.barn_id,
        feeding_location_id=payload.feeding_location_id,
    )

    if payload.history_hours is not None:
        settings["prediction_history_hours"] = payload.history_hours
    if payload.forecast_hours is not None:
        settings["prediction_forecast_hours"] = payload.forecast_hours

    data = load_prediction_input(
        feeding_location_id=payload.feeding_location_id,
        history_hours=int(settings["prediction_history_hours"]),
        forecast_hours=int(settings["prediction_forecast_hours"]),
    )

    feeding_location = data["feeding_location"]
    barn_id = str(feeding_location.get("barn_id"))
    if payload.barn_id and payload.barn_id != barn_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Barn mismatch for feeding location",
        )

    result = generate_feed_forecast(
        history=data["history"],
        feeding_events=data["feeding_events"],
        settings=settings,
    )

    unmapped_events = data["unmapped_events"] if payload.include_unmapped_events else []

    return FeedForecastResponse(
        status=result.get("status", "unknown"),
        feeding_location_id=payload.feeding_location_id,
        barn_id=barn_id,
        generated_at=datetime.utcnow().isoformat() + "Z",
        result=result,
        settings_used=settings,
        unmapped_events=unmapped_events,
    )
