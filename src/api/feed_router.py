import traceback
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from src.api.base_models import (
    DeviceLinkRequest,
    DeviceBarnMappingRequest,
    DeviceLocationMappingRequest,
    FeedingScheduleCreate,
    FeedingScheduleUpdate,
    OneTimeFeedingCreate,
    ThresholdsUpdate,
    FeedLevelPredictRequest,
)
from src.utils.utils import get_current_user
 

feed_router = APIRouter()
logger = logging.getLogger(__name__)


THRESHOLD_DEFAULTS = {
    "heat_stress_thi_threshold": 72,
    "severe_heat_thi_threshold": 80,
    "heat_stress_duration_minutes": 240,
    "severe_heat_duration_minutes": 360,
    "alert_cooldown_hours": 6,
    "feed_stale_minutes": 60,
    "feed_stale_change_percent": 1,
    "low_feed_percent": 20,
    "low_feed_critical_percent": 10,
    "spoilage_feed_percent": 70,
    "spoilage_temp_c": 25,
    "spoilage_stale_hours": 8,
    "feed_rise_percent": 5,
    "feed_rise_lookback_minutes": 60,
    "unexpected_feed_cooldown_minutes": 120,
    "cancel_feed_high_percent": 80,
    "cancel_feed_lookahead_hours": 2,
    "low_feed_recurrence_count": 3,
    "low_feed_recurrence_days": 7,
    "feeding_suggestion_min_kg": 10,
    "moohero_alert_cooldown_hours": 6,
    "health_spike_count": 3,
    "health_spike_hours": 24,
    "health_spike_thi_window_hours": 24,
    "health_spike_thi_delta": 8,
    "health_spike_feed_alert_hours": 12,
}


def _merge_thresholds(*sets):
    result = {}
    for items in sets:
        if items:
            result.update(items)
    return result


def _numeric_only(d: dict) -> dict:
    """Keep only the known numeric threshold keys, dropping non-threshold config
    rows that share the alert_thresholds table (rule_config:*, notification_routing,
    alert_debounce_cycles). Prevents those JSON objects from leaking into the
    thresholds endpoints."""
    return {k: v for k, v in (d or {}).items() if k in THRESHOLD_DEFAULTS}




@feed_router.get(
    "/feed/levels",
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "levels": [
                            {
                                "feeding_location_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
                                "location_name": "North trough",
                                "barn_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                                "feed_level": 42.5,
                                "reading_kind": "feed_level_percentage",
                                "timestamp": "2026-06-17T09:15:00Z",
                            }
                        ],
                        "count": 1,
                    }
                }
            }
        }
    },
)
async def get_feed_levels(
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """Return the latest feed-level reading for every feeding location.

    Supports JSON-LD via `Accept: application/ld+json`.
    """
    try:
        logger.debug("feed_levels request start", extra={"user_id": current_user.get("id")})
        from src.utils.db import PGDB
        from src.utils.jsonld import wants_jsonld, ld_response, feed_level_to_ld
        db = PGDB()
        levels = db.get_latest_feed_levels()
        logger.debug("feed_levels request success", extra={"count": len(levels)})
        if wants_jsonld(request):
            return ld_response([feed_level_to_ld(row) for row in levels])
        return {"levels": levels, "count": len(levels)}
    except Exception:
        logger.exception("feed_levels request failed")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Failed to get feed levels")


@feed_router.get(
    "/feed/devices",
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "devices": [
                            {
                                "device_eui": "A1B2C3D4E5F60718",
                                "display_name": "Feed silo sensor 1",
                                "barn_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                                "last_seen": "2026-06-17T09:10:00Z",
                            }
                        ],
                        "count": 1,
                    }
                }
            }
        }
    },
)
async def list_devices(
    current_user: dict = Depends(get_current_user)
):
    """List all registered IoT devices with their current barn and location mappings."""
    try:
        from src.utils.db import PGDB
        db = PGDB()
        devices = db.list_devices_with_mapping()
        return {"devices": devices, "count": len(devices)}
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Failed to get devices")


@feed_router.post("/feed/devices/link")
async def link_device_to_feeding_location(
    payload: DeviceLinkRequest,
    current_user: dict = Depends(get_current_user)
):
    """Assign an IoT device to a barn (first-step mapping).

    After linking a device to a barn, use `POST /feed/devices/location-mappings` to
    map the device's incoming raw location name strings to specific feeding location UUIDs.
    """
    try:
        from src.utils.db import PGDB
        db = PGDB()
        result = db.set_device_barn(
            device_eui=payload.device_eui,
            barn_id=payload.barn_id,
            display_name=payload.display_name
        )
        return {"message": "Device linked to barn", "mapping": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Failed to link device")


@feed_router.post("/feed/devices/location-mappings")
async def upsert_device_location_mapping(
    payload: DeviceLocationMappingRequest,
    current_user: dict = Depends(get_current_user)
):
    """Map an incoming device location name to a feeding location UUID.

    IoT devices report location names as raw strings. This endpoint tells the system
    which `feeding_location_id` a given string corresponds to, so telemetry is
    attributed to the correct location.
    """
    try:
        from src.utils.db import PGDB
        db = PGDB()
        result = db.upsert_device_location_mapping(
            device_eui=payload.device_eui,
            barn_id=payload.barn_id,
            source_location_key=payload.incoming_feeding_location_name,
            feeding_location_id=payload.feeding_location_id,
        )
        return {"message": "Device location mapping saved", "mapping": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Failed to save device location mapping")


@feed_router.post("/feed/devices/barn-mappings")
async def upsert_device_barn_mapping(
    payload: DeviceBarnMappingRequest,
    current_user: dict = Depends(get_current_user)
):
    """Map an incoming device barn name to a barn UUID.

    IoT devices may report barn names as raw strings. This endpoint tells the system
    which `barn_id` a given string corresponds to.
    """
    try:
        from src.utils.db import PGDB
        db = PGDB()
        result = db.upsert_device_barn_mapping(
            device_eui=payload.device_eui,
            source_barn_key=payload.incoming_barn_name,
            barn_id=payload.barn_id,
        )
        return {"message": "Device barn mapping saved", "mapping": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Failed to save device barn mapping")


@feed_router.get("/feed/devices/location-mappings")
async def list_device_location_mappings(
    device_eui: str = Query(None),
    barn_id: str = Query(None),
    current_user: dict = Depends(get_current_user)
):
    """List existing device → feeding location name mappings, optionally filtered by device or barn."""
    try:
        from src.utils.db import PGDB
        db = PGDB()
        rows = db.list_device_location_mappings(device_eui=device_eui, barn_id=barn_id)
        return {"mappings": rows, "count": len(rows)}
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Failed to list device location mappings")


@feed_router.get("/feed/devices/barn-mappings")
async def list_device_barn_mappings(
    device_eui: str = Query(None),
    barn_id: str = Query(None),
    current_user: dict = Depends(get_current_user)
):
    """List existing device → barn name mappings, optionally filtered by device or barn."""
    try:
        from src.utils.db import PGDB
        db = PGDB()
        rows = db.list_device_barn_mappings(device_eui=device_eui, barn_id=barn_id)
        return {"mappings": rows, "count": len(rows)}
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Failed to list device barn mappings")


@feed_router.get("/feed/devices/incoming-location-names")
async def list_incoming_location_names(
    device_eui: str = Query(None),
    barn_id: str = Query(None),
    hours: int = Query(168, ge=1, le=2160),
    current_user: dict = Depends(get_current_user)
):
    """List the raw location name strings recently sent by IoT devices.

    Useful for discovering which incoming names still need to be mapped to feeding
    locations via `POST /feed/devices/location-mappings`. `hours` controls how far
    back to look (max 2160 = 90 days).
    """
    try:
        from src.utils.db import PGDB
        db = PGDB()
        rows = db.list_incoming_location_names(
            device_eui=device_eui,
            barn_id=barn_id,
            hours=hours,
        )
        return {"incoming_location_names": rows, "count": len(rows)}
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Failed to list incoming location names")


@feed_router.get("/feed/devices/incoming-barn-names")
async def list_incoming_barn_names(
    device_eui: str = Query(None),
    hours: int = Query(168, ge=1, le=2160),
    current_user: dict = Depends(get_current_user)
):
    """List the raw barn name strings recently sent by IoT devices.

    Useful for discovering which names need to be mapped via `POST /feed/devices/barn-mappings`.
    """
    try:
        from src.utils.db import PGDB
        db = PGDB()
        rows = db.list_incoming_barn_names(
            device_eui=device_eui,
            hours=hours,
        )
        return {"incoming_barn_names": rows, "count": len(rows)}
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Failed to list incoming barn names")


@feed_router.get(
    "/feed/thresholds",
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "scope": "global",
                        "thresholds": {
                            "low_feed_percent": 20,
                            "spoilage_feed_percent": 70,
                            "heat_stress_thi_threshold": 72,
                            "severe_heat_thi_threshold": 80,
                        },
                        "overrides": {"low_feed_percent": 20},
                    }
                }
            }
        }
    },
)
async def get_global_thresholds(current_user: dict = Depends(get_current_user)):
    """Return the resolved global threshold settings.

    Returns system defaults merged with any global overrides. Available keys include
    `low_feed_percent`, `spoilage_feed_percent`, `heat_stress_thi_threshold`,
    `severe_heat_thi_threshold`, and many others. The `overrides` field shows only
    values that have been explicitly set (differing from defaults).
    """
    from src.utils.db import PGDB
    db = PGDB()
    global_thresholds = _numeric_only(db.get_thresholds("global"))
    thresholds = _merge_thresholds(THRESHOLD_DEFAULTS, global_thresholds)
    return {
        "scope": "global",
        "thresholds": thresholds,
        "overrides": global_thresholds,
    }


@feed_router.get("/feed/prediction-settings")
async def get_prediction_settings(
    scope_type: str = Query("global"),
    scope_id: str = Query(None),
    current_user: dict = Depends(get_current_user),
):
    """Return feed prediction model settings from the prediction microservice.

    Returns 502 if the prediction service (port 8015) is unavailable.
    """
    try:
        from src.services.prediction_client import PREDICTION_SERVICE_URL
        import httpx

        params = {"scope_type": scope_type}
        if scope_id:
            params["scope_id"] = scope_id

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{PREDICTION_SERVICE_URL}/api/v1/settings",
                params=params,
            )

        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=502,
            detail=f"Prediction service error: {e.response.text}",
        )
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get prediction settings: {str(e)}",
        )


@feed_router.put("/feed/thresholds")
async def update_global_thresholds(
    payload: ThresholdsUpdate,
    current_user: dict = Depends(get_current_user)
):
    """Overwrite global threshold values.

    Pass only the keys you want to change in `thresholds`. Unset keys keep their
    current value. Changes apply to all barns that do not have location-level overrides.
    """
    from src.utils.db import PGDB
    db = PGDB()
    updated = db.upsert_thresholds(
        "global",
        None,
        _numeric_only(payload.thresholds),
        current_user.get("id")
    )
    return {"scope": "global", "thresholds": _numeric_only(updated)}


def _split_alert_settings(raw: dict) -> dict:
    """Split a raw {key: value} threshold map into the alert-settings shape."""
    rules, routing, debounce = {}, None, None
    for key, value in (raw or {}).items():
        if key.startswith("rule_config:"):
            rules[key.split(":", 1)[1]] = value
        elif key == "notification_routing":
            routing = value
        elif key == "alert_debounce_cycles":
            debounce = value
    return {"rules": rules, "notification_routing": routing, "debounce_cycles": debounce}


@feed_router.get("/feed/alert-settings")
async def get_alert_settings(
    scope_type: str = Query("global", description="global | feeding_location"),
    scope_id: str = Query(None, description="feeding_location_id when scope_type=feeding_location"),
    current_user: dict = Depends(get_current_user),
):
    """Return per-rule alert config plus the global notification routing + debounce.

    `rules` maps each rule_type (low_feed, heat_stress, spoilage_risk,
    health_spike, ...) to its config object: {enabled, severity,
    prediction_enabled, prediction_horizon_hours, notify_on_predict}. At
    feeding_location scope only the keys overridden there are returned; numeric
    thresholds (low_feed_percent, etc.) live under `/feed/thresholds`.
    """
    from src.utils.db import PGDB
    db = PGDB()
    raw = db.get_thresholds(scope_type, None if scope_type == "global" else scope_id)
    return {"scope_type": scope_type, "scope_id": scope_id, **_split_alert_settings(raw)}


@feed_router.put("/feed/alert-settings")
async def update_alert_settings(
    payload: Dict[str, Any],
    current_user: dict = Depends(get_current_user),
):
    """Update per-rule alert config and/or notification routing + debounce.

    Body: {scope_type?, scope_id?, rules?: {<rule_type>: {...}},
    notification_routing?: {...}, debounce_cycles?: int}. Only the keys present are
    written; others keep their current value. Reuses the alert_thresholds store, so
    feeding_location entries override global.
    """
    from src.utils.db import PGDB
    db = PGDB()
    scope_type = payload.get("scope_type", "global")
    scope_id = payload.get("scope_id")

    updates = {}
    for rule_type, cfg in (payload.get("rules") or {}).items():
        updates[f"rule_config:{rule_type}"] = cfg
    if payload.get("notification_routing") is not None:
        updates["notification_routing"] = payload["notification_routing"]
    if payload.get("debounce_cycles") is not None:
        updates["alert_debounce_cycles"] = payload["debounce_cycles"]

    if updates:
        db.upsert_thresholds(
            scope_type,
            None if scope_type == "global" else scope_id,
            updates,
            current_user.get("id"),
        )

    raw = db.get_thresholds(scope_type, None if scope_type == "global" else scope_id)
    return {"scope_type": scope_type, "scope_id": scope_id, **_split_alert_settings(raw)}


@feed_router.put("/feed/prediction-settings")
async def update_prediction_settings(
    payload: Dict[str, Any],
    current_user: dict = Depends(get_current_user),
):
    """Update feed prediction model settings on the prediction microservice.

    Returns 502 if the prediction service (port 8015) is unavailable.
    """
    try:
        from src.services.prediction_client import PREDICTION_SERVICE_URL
        import httpx

        payload = dict(payload)
        payload["updated_by"] = current_user.get("id")

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.put(
                f"{PREDICTION_SERVICE_URL}/api/v1/settings",
                json=payload,
            )

        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=502,
            detail=f"Prediction service error: {e.response.text}",
        )
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update prediction settings: {str(e)}",
        )


@feed_router.get("/feed/feeding-locations/{feeding_location_id}/thresholds")
async def get_feeding_location_thresholds(
    feeding_location_id: str,
):
    """Return resolved thresholds for a specific feeding location.

    Returns system defaults merged with global overrides merged with location-level overrides.
    The `overrides` field shows only location-specific values; `global_overrides` shows global ones.
    """
    from src.utils.db import PGDB
    db = PGDB()
    location = db.get_feeding_location_by_id(feeding_location_id)
    if not location:
        raise HTTPException(status_code=404, detail="Feeding location not found")
    barn_id = location.get("barn_id")
    global_thresholds = _numeric_only(db.get_thresholds("global"))
    location_thresholds = _numeric_only(db.get_thresholds("feeding_location", feeding_location_id))
    resolved = _merge_thresholds(THRESHOLD_DEFAULTS, global_thresholds, location_thresholds)
    return {
        "scope": "feeding_location",
        "scope_id": feeding_location_id,
        "barn_id": barn_id,
        "thresholds": resolved,
        "global_overrides": global_thresholds,
        "overrides": location_thresholds
    }


@feed_router.put("/feed/feeding-locations/{feeding_location_id}/thresholds")
async def update_feeding_location_thresholds(
    feeding_location_id: str,
    payload: ThresholdsUpdate,
    current_user: dict = Depends(get_current_user)
):
    """Set threshold overrides for a specific feeding location.

    Overrides take precedence over global settings. Pass only the keys you want to
    override; unset keys inherit from the global or default values.
    """
    from src.utils.db import PGDB
    db = PGDB()
    location = db.get_feeding_location_by_id(feeding_location_id)
    if not location:
        raise HTTPException(status_code=404, detail="Feeding location not found")
    updated = db.upsert_thresholds(
        "feeding_location",
        feeding_location_id,
        _numeric_only(payload.thresholds),
        current_user.get("id")
    )
    return {
        "scope": "feeding_location",
        "scope_id": feeding_location_id,
        "thresholds": _numeric_only(updated)
    }


@feed_router.get("/feed/feeding-locations/{feeding_location_id}/forecast")
async def get_feeding_location_forecast(
    feeding_location_id: str,
    history_hours: int = Query(None, ge=1, le=2160),
    forecast_hours: int = Query(None, ge=1, le=240),
    current_user: dict = Depends(get_current_user),
):
    """Return the feed-level forecast for a specific feeding location.

    Proxies to the prediction microservice. `history_hours` sets how much historical
    telemetry the model uses; `forecast_hours` controls how far ahead to predict (max 240 h).
    Returns 502 if the prediction service (port 8015) is unavailable.
    """
    try:
        from src.utils.db import PGDB
        from src.services.prediction_client import (
            get_feed_forecast_from_prediction_service,
        )
        from src.api.anchor_router import get_anchor_window
        import httpx

        db = PGDB()

        location = db.get_feeding_location_by_id(feeding_location_id)
        if not location:
            raise HTTPException(status_code=404, detail="Feeding location not found")

        barn_id = str(location.get("barn_id"))

        start_time, end_time = get_anchor_window(history_hours=history_hours or 168)

        forecast = await get_feed_forecast_from_prediction_service(
            feeding_location_id=feeding_location_id,
            barn_id=barn_id,
            history_hours=history_hours,
            forecast_hours=forecast_hours,
            start_time=start_time,
            end_time=end_time,
        )

        return forecast

    except HTTPException:
        raise
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=502,
            detail=f"Prediction service error: {e.response.text}",
        )
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get feed forecast: {str(e)}",
        )


@feed_router.post("/predict/feed-level")
async def predict_feed_level(
    payload: FeedLevelPredictRequest,
    current_user: dict = Depends(get_current_user),
):
    """Predict the future feed level for a feeding location.

    Prefer `GET /feed/feeding-locations/{id}/forecast` for new integrations.
    Proxies to the prediction microservice; returns 502 if unavailable.
    """
    try:
        from src.utils.db import PGDB
        from src.services.prediction_client import (
            get_feed_forecast_from_prediction_service,
        )
        import httpx

        db = PGDB()

        if not payload.feeding_location_id:
            raise HTTPException(
                status_code=400,
                detail="feeding_location_id is required",
            )

        location = db.get_feeding_location_by_id(payload.feeding_location_id)
        if not location:
            raise HTTPException(status_code=404, detail="Feeding location not found")

        from src.api.anchor_router import get_anchor_window
        start_time, end_time = get_anchor_window(history_hours=168)

        forecast = await get_feed_forecast_from_prediction_service(
            feeding_location_id=payload.feeding_location_id,
            barn_id=payload.barn_id,
            forecast_hours=payload.horizon_hours,
            start_time=start_time,
            end_time=end_time,
        )

        return forecast

    except HTTPException:
        raise
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=502,
            detail=f"Prediction service error: {e.response.text}",
        )
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get feed forecast: {str(e)}",
        )


@feed_router.get(
    "/feed/alerts",
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "alerts": [
                            {
                                "id": "b2c3d4e5-6789-40de-944b-e07fc1f90ae7",
                                "alert_type": "low_feed",
                                "status": "active",
                                "barn_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                                "feeding_location_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
                                "message": "Feed level below 20% at North trough",
                                "created_at": "2026-06-17T08:00:00Z",
                            }
                        ],
                        "count": 1,
                    }
                }
            }
        }
    },
)
async def get_feed_alerts(
    request: Request,
    barn_id: str = Query(None),
    feeding_location_id: str = Query(None),
    alert_type: str = Query(None),
    status: str = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_user)
):
    """Return feed alerts with optional filtering.

    Filter by `barn_id`, `feeding_location_id`, `alert_type`, or `status` (active/resolved).
    Known `alert_type` values: `low_feed`, `spoilage_risk`, `unexpected_feed_rise`.
    Supports JSON-LD via `Accept: application/ld+json`.
    """
    try:
        from src.utils.db import PGDB
        from src.utils.jsonld import wants_jsonld, ld_response, feed_alert_to_ld
        db = PGDB()
        alerts = db.get_alerts(
            barn_id=barn_id,
            feeding_location_id=feeding_location_id,
            status=status,
            limit=limit,
            offset=offset
        )
        if alert_type:
            alerts = [a for a in alerts if a.get("alert_type") == alert_type]
        if wants_jsonld(request):
            return ld_response([feed_alert_to_ld(a) for a in alerts])
        return {"alerts": alerts, "count": len(alerts)}
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Failed to get alerts")


@feed_router.get("/feed/alerts/new")
async def get_new_alerts(
    request: Request,
    barn_id: str = Query(None),
    feeding_location_id: str = Query(None),
    alert_type: str = Query(None),
    origin: str = Query(
        "observed",
        description="observed (real-time, default) | predicted (forecast) | all (both)",
    ),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_user)
):
    """Return active (unresolved) feed alerts.

    Each alert carries `origin` ("observed" | "predicted") and, for predicted
    alerts, `predicted_for` (the forecast time the condition is expected). Use
    `origin=all` to fetch both and split them into Now/Upcoming client-side;
    defaults to observed-only for backward compatibility.

    Supports JSON-LD via `Accept: application/ld+json`.
    """
    try:
        from src.utils.db import PGDB
        from src.utils.jsonld import wants_jsonld, ld_response, feed_alert_to_ld
        db = PGDB()
        origin_filter = None if origin == "all" else origin
        alerts = db.get_alerts(
            barn_id=barn_id,
            feeding_location_id=feeding_location_id,
            status="active",
            origin=origin_filter,
            limit=limit,
            offset=offset
        )
        if alert_type:
            alerts = [a for a in alerts if a.get("alert_type") == alert_type]
        if wants_jsonld(request):
            return ld_response([feed_alert_to_ld(a) for a in alerts])
        return {"alerts": alerts, "count": len(alerts)}
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Failed to get alerts")


@feed_router.get("/feed/alerts/{alert_id}")
async def get_feed_alert(
    alert_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Return a single feed alert by ID. Returns 404 if not found."""
    try:
        from src.utils.db import PGDB
        db = PGDB()
        alert = db.get_alert_by_id(alert_id)
        if not alert:
            raise HTTPException(status_code=404, detail="Alert not found")
        return alert
    except HTTPException:
        raise
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Failed to get alert")


@feed_router.put("/feed/alerts/{alert_id}/resolve")
async def resolve_feed_alert(
    alert_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Mark a feed alert as resolved. Returns 404 if not found."""
    try:
        from src.utils.db import PGDB
        db = PGDB()
        alert = db.get_alert_by_id(alert_id)
        if not alert:
            raise HTTPException(status_code=404, detail="Alert not found")
        db.resolve_alert(alert_id)
        return {"message": "Alert resolved"}
    except HTTPException:
        raise
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Failed to resolve alert")


@feed_router.delete("/feed/alerts/clear")
async def clear_feed_alerts(
    barn_id: str = Query(None),
    feeding_location_id: str = Query(None),
    alert_type: str = Query(None),
    status: str = Query(None),
    origin: str = Query(None, description="observed | predicted; omit for both"),
    confirm_all: bool = Query(False, description="Set true to clear without filters"),
    hard_delete: bool = Query(False, description="Set true for permanent delete, false to resolve"),
    current_user: dict = Depends(get_current_user),
):
    """
    Bulk clear alerts.

    - Default behavior: marks matched alerts as resolved.
    - `hard_delete=true` permanently deletes matched rows.
    - Safety: if no filters are provided, `confirm_all=true` is required.
    - `origin=observed` clears only real-time alerts; predicted alerts are managed
      by the engine (they would just reappear on the next cycle), so the dashboard's
      "remove all" scopes to observed.
    """
    try:
        from src.utils.db import PGDB

        if not any([barn_id, feeding_location_id, alert_type, status, origin]) and not confirm_all:
            raise HTTPException(
                status_code=400,
                detail="No filters provided. Set confirm_all=true to clear all alerts.",
            )

        db = PGDB()
        cleared_count = db.clear_alerts(
            barn_id=barn_id,
            feeding_location_id=feeding_location_id,
            alert_type=alert_type,
            status=status,
            origin=origin,
            hard_delete=hard_delete,
        )

        return {
            "message": "Alerts cleared successfully",
            "mode": "deleted" if hard_delete else "resolved",
            "cleared_count": cleared_count,
            "filters": {
                "barn_id": barn_id,
                "feeding_location_id": feeding_location_id,
                "alert_type": alert_type,
                "status": status,
                "origin": origin,
                "confirm_all": confirm_all,
            },
        }
    except HTTPException:
        raise
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Failed to clear alerts")


@feed_router.post("/schedules")
async def create_feeding_schedule(
    schedule: "FeedingScheduleCreate",
    current_user: dict = Depends(get_current_user)
):
    """Create a recurring feeding schedule and generate calendar events for it.

    `days_of_week`: list of integers 0–6 (Monday = 0, Sunday = 6).
    `time_start` / `time_end`: 24-hour strings, e.g. `"06:30"` and `"08:30"`, defining
    the window in which the feeding is expected. This window is also used directly for
    missed-feeding detection. If `time_end` is earlier than `time_start` the window
    crosses midnight.
    Calendar events are automatically generated for the next 30 days after creation.
    """
    try:
        from src.utils.db import PGDB
        from src.services.feeding_event_generator import feeding_event_generator

        db = PGDB()
        result = db.create_feeding_schedule(
            barn_id=schedule.barn_id,
            feeding_location_id=schedule.feeding_location_id,
            schedule_name=schedule.schedule_name,
            days_of_week=schedule.days_of_week,
            time_start=schedule.time_start,
            time_end=schedule.time_end,
            quantity_kg=schedule.quantity_kg,
            notes=schedule.notes
        )
        
        event_result = await feeding_event_generator.generate_events_for_schedule_id(result['id'])
        
        return {
            "message": "Feeding schedule created successfully",
            "schedule": result,
            "events": event_result
        }
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Failed to create feeding schedule")


@feed_router.post("/feed/one-time-activity")
async def create_one_time_feeding_activity(
    payload: OneTimeFeedingCreate,
    current_user: dict = Depends(get_current_user)
):
    """Create a one-time feeding activity in the calendar.

    If `end_datetime` is omitted, it defaults to `start_datetime + 1 hour`.
    """
    try:
        from src.utils.db import PGDB
        from datetime import timedelta

        db = PGDB()
        end_datetime = payload.end_datetime
        if not end_datetime:
            end_datetime = payload.start_datetime + timedelta(hours=1)
        title = payload.title or "One-time Feeding"

        result = db.create_one_time_feeding_activity(
            barn_id=payload.barn_id,
            feeding_location_id=payload.feeding_location_id,
            start_datetime=payload.start_datetime,
            end_datetime=end_datetime,
            title=title,
            notes=payload.notes,
            quantity_kg=payload.quantity_kg
        )
        return {
            "message": "One-time feeding activity created",
            "calendar_activity": result.get("calendar_activity"),
            "schedule": result.get("schedule")
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Failed to create one-time feeding activity")


@feed_router.get(
    "/schedules",
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "schedules": [
                            {
                                "id": "9d8c7b6a-5432-40de-944b-e07fc1f90ae7",
                                "barn_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                                "feeding_location_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
                                "schedule_name": "Weekday morning feed",
                                "days_of_week": [0, 1, 2, 3, 4],
                                "time_start": "06:30",
                                "time_end": "08:30",
                                "quantity_kg": 25.0,
                                "is_active": True,
                            }
                        ],
                        "count": 1,
                    }
                }
            }
        }
    },
)
async def get_feeding_schedules(
    barn_id: str = Query(None),
    feeding_location_id: str = Query(None),
    is_active: bool = Query(True),
    current_user: dict = Depends(get_current_user)
):
    """List feeding schedules, optionally filtered by barn or location.

    Only active schedules are returned by default. Pass `is_active=false` to include
    deactivated schedules.
    """
    try:
        from src.utils.db import PGDB
        db = PGDB()
        schedules = db.get_feeding_schedules(
            barn_id=barn_id,
            feeding_location_id=feeding_location_id,
            is_active=is_active
        )
        return {"schedules": schedules, "count": len(schedules)}
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Failed to get feeding schedules")


@feed_router.get("/schedules/{schedule_id}")
async def get_feeding_schedule(
    schedule_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Return a single feeding schedule by ID. Returns 404 if not found."""
    try:
        from src.utils.db import PGDB
        db = PGDB()
        schedule = db.get_feeding_schedule_by_id(schedule_id)
        if not schedule:
            raise HTTPException(status_code=404, detail="Schedule not found")
        return schedule
    except HTTPException:
        raise
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Failed to get feeding schedule")


@feed_router.put("/schedules/{schedule_id}")
async def update_feeding_schedule(
    schedule_id: str,
    updates: "FeedingScheduleUpdate",
    current_user: dict = Depends(get_current_user)
):
    """Update a feeding schedule. Only provided fields are changed.

    If the schedule remains active after the update, calendar events are regenerated.
    Set `is_active=false` to deactivate without deleting.
    """
    try:
        from src.utils.db import PGDB
        from src.services.feeding_event_generator import feeding_event_generator
        
        db = PGDB()
        result = db.update_feeding_schedule(
            schedule_id=schedule_id,
            schedule_name=updates.schedule_name,
            days_of_week=updates.days_of_week,
            time_start=updates.time_start,
            time_end=updates.time_end,
            quantity_kg=updates.quantity_kg,
            notes=updates.notes,
            is_active=updates.is_active
        )
        if not result:
            raise HTTPException(status_code=404, detail="Schedule not found")
        
        if result.get('is_active'):
            event_result = await feeding_event_generator.generate_events_for_schedule_id(schedule_id)
            return {
                "message": "Schedule updated successfully",
                "schedule": result,
                "events": event_result
            }
        
        return {"message": "Schedule updated successfully", "schedule": result}
    except HTTPException:
        raise
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Failed to update feeding schedule")


@feed_router.delete("/schedules/{schedule_id}")
async def delete_feeding_schedule(
    schedule_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Deactivate a feeding schedule (soft delete).

    The record is retained with `is_active=false`. Returns 404 if not found.
    """
    try:
        from src.utils.db import PGDB
        db = PGDB()
        success = db.delete_feeding_schedule(schedule_id)
        if not success:
            raise HTTPException(status_code=404, detail="Schedule not found")
        return {"message": "Schedule deactivated successfully"}
    except HTTPException:
        raise
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Failed to delete feeding schedule")


@feed_router.post("/schedules/sync-from-calendar")
async def sync_calendar_activities(
    current_user: dict = Depends(get_current_user)
):
    """Re-sync feeding events from Farm Calendar into the local schedule store.

    Looks back 7 days and ahead 30 days. Call this after making changes in Farm Calendar
    that should be reflected in feed forecasts and history charts.
    """
    try:
        from src.utils.db import PGDB
        db = PGDB()
        synced_count = db.sync_farm_calendar_feeding_activities(
            days_back=7,
            days_ahead=30
        )
        return {
            "status": "success",
            "synced": synced_count,
            "message": f"Synced {synced_count} feeding activities from Farm Calendar"
        }
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Failed to sync calendar activities")


@feed_router.post("/schedules/{schedule_id}/generate-events")
async def generate_events_for_schedule(
    schedule_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Manually trigger calendar event generation for a specific schedule.

    Events are also generated automatically on schedule create/update.
    Returns 404 if the schedule does not exist.
    """
    try:
        from src.services.feeding_event_generator import feeding_event_generator
        result = await feeding_event_generator.generate_events_for_schedule_id(schedule_id)
        return {
            "message": "Events generated successfully",
            **result
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Failed to generate events")


