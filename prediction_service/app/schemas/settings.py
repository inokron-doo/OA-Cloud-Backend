from pydantic import BaseModel


class PredictionSettingsUpdate(BaseModel):
    scope_type: str
    scope_id: str | None = None
    settings: dict
    updated_by: int | None = None
