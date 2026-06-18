from pydantic import BaseModel, Field


class FeedForecastRequest(BaseModel):
    feeding_location_id: str
    barn_id: str | None = None
    history_hours: int | None = Field(default=None, ge=1, le=2160)
    forecast_hours: int | None = Field(default=None, ge=1, le=240)
    include_unmapped_events: bool = True


class FeedForecastResponse(BaseModel):
    status: str
    feeding_location_id: str
    barn_id: str
    generated_at: str
    result: dict
    settings_used: dict
    unmapped_events: list = []
