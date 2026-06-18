import re
import traceback
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from src.utils.db import PGDB
from src.utils.utils import get_current_user
from src.api.base_models import FeedingLocationUpdate


barns_router = APIRouter()
db = PGDB()


_QTY_PATTERN = re.compile(r"\((?P<qty>[\d.]+)\s*kg\)", re.IGNORECASE)


@barns_router.get(
    "/farms",
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "farms": [
                            {
                                "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                                "name": "Greenfield Farm",
                                "moohero_id": 42,
                            }
                        ],
                        "count": 1,
                    }
                }
            }
        }
    },
)
async def get_all_farms(current_user: dict = Depends(get_current_user)):
    """Return all farms the current user has access to."""
    try:
        results = db.get_all_farms()
        return {
            "farms": results if results else [],
            "count": len(results) if results else 0
        }
    except Exception:
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail="Failed to fetch farms"
        )


@barns_router.get("/farms/{farm_id}/barns")
async def get_barns_by_farm(
    farm_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Return all barns belonging to a specific farm."""
    try:
        results = db.get_barns_by_farm_id(farm_id)
        return {
            "farm_id": farm_id,
            "barns": results if results else [],
            "count": len(results) if results else 0
        }
    except Exception:
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail="Failed to fetch barns for farm"
        )


@barns_router.get("/farms/{farm_id}")
async def get_farm_by_id(
    farm_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Return a single farm by its UUID. Returns 404 if not found."""
    try:
        result = db.get_farm_by_id(farm_id)
        if not result:
            raise HTTPException(status_code=404, detail="Farm not found")
        return result
    except HTTPException:
        raise
    except Exception:
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail="Failed to fetch farm"
        )




@barns_router.get(
    "/{barn_id}/feeding-locations",
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "barn_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                        "feeding_locations": [
                            {
                                "id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
                                "name": "North trough",
                                "barn_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                                "is_hidden": False,
                                "external_id": "trough_north",
                            }
                        ],
                        "count": 1,
                    }
                }
            }
        }
    },
)
async def get_feeding_locations_by_barn(
    barn_id: str,
    include_hidden: bool = Query(False),
    current_user: dict = Depends(get_current_user)
):
    """Return feeding locations in a barn.

    Hidden locations are excluded by default; pass `include_hidden=true` to include them.
    Feeding locations are discovered automatically from IoT device telemetry — they
    cannot be created manually. Use rename/hide/delete to manage discovered locations.
    """
    try:
        results = db.get_feeding_locations_by_barn(barn_id, include_hidden=include_hidden)
        return {
            "barn_id": barn_id,
            "feeding_locations": results if results else [],
            "count": len(results) if results else 0
        }
    except Exception:
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail="Failed to fetch feeding locations for barn"
        )


# Feeding locations are discovery-only: they are created by the IoT ingest from
# device data (identity = the device key). There is intentionally no manual
# "create by name" endpoint, which used to produce stray locations that never
# matched any device. Manage discovered locations via rename / hide / delete.


@barns_router.put("/feeding-locations/{feeding_location_id}")
async def update_feeding_location(
    feeding_location_id: str,
    request: FeedingLocationUpdate,
    current_user: dict = Depends(get_current_user)
):
    """Rename a feeding location and/or toggle its visibility.

    Feeding locations are discovered automatically from device telemetry and cannot
    be created by name. Use this endpoint to rename or hide a discovered location.
    Omit fields you do not want to change.
    """
    try:
        existing = db.get_feeding_location_by_id(feeding_location_id)
        if not existing:
            raise HTTPException(status_code=404, detail="Feeding location not found")

        result = db.update_feeding_location(
            feeding_location_id=feeding_location_id,
            name=request.name,
            is_hidden=request.is_hidden
        )

        return {
            "message": "Feeding location updated successfully",
            "feeding_location": result
        }
    except HTTPException:
        raise
    except Exception:
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail="Failed to update feeding location"
        )


@barns_router.patch("/feeding-locations/{feeding_location_id}/visibility")
async def set_feeding_location_visibility(
    feeding_location_id: str,
    hidden: bool = Query(...),
    current_user: dict = Depends(get_current_user)
):
    """Show or hide a specific feeding location.

    Pass `hidden=true` to hide, `hidden=false` to show. Prefer hiding over deleting
    locations that have telemetry history.
    """
    try:
        existing = db.get_feeding_location_by_id(feeding_location_id)
        if not existing:
            raise HTTPException(status_code=404, detail="Feeding location not found")

        result = db.update_feeding_location(
            feeding_location_id=feeding_location_id,
            is_hidden=hidden
        )
        return {
            "message": "Feeding location visibility updated",
            "feeding_location": result
        }
    except HTTPException:
        raise
    except Exception:
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail="Failed to update feeding location visibility"
        )


@barns_router.delete("/feeding-locations/{feeding_location_id}")
async def delete_feeding_location(
    feeding_location_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Permanently delete a feeding location.

    Returns 409 if the location has telemetry history — use the visibility endpoint
    to hide it instead of deleting it.
    """
    try:
        existing = db.get_feeding_location_by_id(feeding_location_id)
        if not existing:
            raise HTTPException(status_code=404, detail="Feeding location not found")

        db.delete_feeding_location(feeding_location_id)

        return {
            "message": "Feeding location deleted successfully"
        }
    except ValueError as e:
        # Has telemetry history - caller should hide it instead.
        raise HTTPException(status_code=409, detail=str(e))
    except HTTPException:
        raise
    except Exception:
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail="Failed to delete feeding location"
        )


def _parse_quantity_kg(title):
    if not title:
        return None
    match = _QTY_PATTERN.search(title)
    if match:
        return float(match.group("qty"))
    return None


@barns_router.get(
    "/feeding-locations/{feeding_location_id}/history",
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "feeding_location_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
                        "feeding_location_name": "North trough",
                        "barn_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                        "hours_requested": 168,
                        "low_threshold": 20.0,
                        "data_points": 2,
                        "readings": [
                            {"timestamp": "2026-06-17T06:00:00Z", "numeric_value": 80.0,
                             "reading_kind": "feed_level_percentage"},
                            {"timestamp": "2026-06-17T09:00:00Z", "numeric_value": 42.5,
                             "reading_kind": "feed_level_percentage"},
                        ],
                        "feeding_events": [
                            {
                                "feeding_location": {"id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
                                                     "name": "North trough"},
                                "feeding_activity": {"id": "act-1", "title": "Morning feeding (25 kg)",
                                                     "quantity_kg": 25.0},
                                "timestamp": "2026-06-17T07:00:00Z",
                                "start_datetime": "2026-06-17T07:00:00Z",
                                "end_datetime": "2026-06-17T08:00:00Z",
                            }
                        ],
                        "feeding_events_count": 1,
                    }
                }
            }
        }
    },
)
async def get_feeding_location_history(
    feeding_location_id: str,
    request: Request,
    hours: int = Query(168, description="Hours of historical data", ge=1, le=168),
    start_time: datetime = Query(None, description="Optional start datetime for anchoring"),
    end_time: datetime = Query(None, description="Optional end datetime for anchoring"),
    current_user: dict = Depends(get_current_user)
):
    """
    Get historical feeding data for a specific feeding location.
    Returns telemetry readings for graphing.

    Args:
        feeding_location_id: UUID of the feeding location
        hours: Number of hours of history (default 168, max 168 = 7 days)
    """
    try:
        from src.api.anchor_router import get_anchor_window
        if start_time is None and end_time is None:
            start_time, end_time = get_anchor_window(history_hours=hours)

        location = db.get_feeding_location_by_id(feeding_location_id)
        if not location:
            raise HTTPException(status_code=404, detail="Feeding location not found")

        history = db.get_feeding_location_history(
            feeding_location_id, 
            hours=hours, 
            start_time=start_time, 
            end_time=end_time
        )
        events = db.get_farm_calendar_feeding_events_for_feeding_location(
            feeding_location_id=feeding_location_id,
            barn_id=location.get("barn_id"),
            hours=hours,
            limit=2000,
            start_time=start_time,
            end_time=end_time,
        )
        if not events:
            events = db.get_feeding_events_from_schedules(
                feeding_location_id=feeding_location_id,
                barn_id=location.get("barn_id"),
                hours=hours,
                limit=2000,
            )

        try:
            low_threshold = float(db.get_threshold_value(
                "low_feed_percent",
                barn_id=location.get("barn_id"),
                feeding_location_id=feeding_location_id,
                default=20.0
            ))
        except (ValueError, TypeError):
            low_threshold = 20.0

        from src.utils.jsonld import wants_jsonld, ld_response, feed_level_to_ld
        if wants_jsonld(request):
            fl_rows = [
                {
                    **dict(r),
                    "feeding_location_id": feeding_location_id,
                    "feed_level": r.get("numeric_value"),
                    "location_name": location.get("name"),
                    "external_id": location.get("external_id"),
                }
                for r in (history or [])
                if r.get("reading_kind") == "feed_level_percentage"
            ]
            return ld_response([feed_level_to_ld(r) for r in fl_rows])

        return {
            "feeding_location_id": feeding_location_id,
            "feeding_location_name": location.get('name'),
            "barn_id": location.get('barn_id'),
            "hours_requested": hours,
            "low_threshold": low_threshold,
            "data_points": len(history) if history else 0,
            "readings": history if history else [],
            "feeding_events": [
                {
                    "feeding_location": {
                        "id": feeding_location_id,
                        "name": location.get("name"),
                    },
                    "feeding_activity": {
                        "id": e.get("feeding_activity_id"),
                        "title": e.get("title"),
                        "details": e.get("details"),
                        "quantity_kg": _parse_quantity_kg(e.get("title")),
                    },
                    "timestamp": e.get("timestamp"),
                    "start_datetime": e.get("timestamp"),
                    "end_datetime": e.get("end_datetime"),
                }
                for e in (events or [])
            ],
            "feeding_events_count": len(events) if events else 0,
        }
    except HTTPException:
        raise
    except Exception:
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail="Failed to fetch feeding location history"
        )


@barns_router.get(
    "/barns/{barn_id}",
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                        "name": "Barn 1",
                        "farm_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                        "latitude": 48.21,
                        "longitude": 16.37,
                    }
                }
            }
        }
    },
)
async def get_barn_by_id(
    barn_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Return a single barn by its UUID, including latitude/longitude. Returns 404 if not found."""
    try:
        result = db.get_barn_by_id(barn_id)
        if not result:
            raise HTTPException(status_code=404, detail="Barn not found")
        return result
    except HTTPException:
        raise
    except Exception:
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail="Failed to get barn details"
        )

@barns_router.get("/feeding-locations")
async def get_all_feeding_locations(
    current_user: dict = Depends(get_current_user)
):
    """Return all feeding locations across all barns, with barn metadata included."""
    try:
        results = db.get_all_feeding_locations_with_barns()
        return {
            "feeding_locations": results if results else [],
            "count": len(results) if results else 0
        }
    except Exception:
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail="Failed to fetch feeding locations"
        )