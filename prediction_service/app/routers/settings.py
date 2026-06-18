from fastapi import APIRouter, Body, Query

from app.db import db
from app.schemas.settings import PredictionSettingsUpdate

router = APIRouter()


@router.get("/api/v1/settings")
def read_settings(
    scope_type: str = Query(default="global"),
    scope_id: str | None = Query(default=None),
) -> dict:
    rows = db.get_prediction_settings(scope_type, scope_id)
    settings = {row["key"]: row["value"] for row in rows}
    return {
        "scope_type": scope_type,
        "scope_id": scope_id,
        "settings": settings,
    }


@router.put("/api/v1/settings")
def update_settings(payload: PredictionSettingsUpdate = Body(...)) -> dict:
    db.create_prediction_settings_table()
    db.upsert_prediction_settings(
        scope_type=payload.scope_type,
        scope_id=payload.scope_id,
        settings_data=payload.settings,
        updated_by=payload.updated_by,
    )
    return {"status": "ok"}
