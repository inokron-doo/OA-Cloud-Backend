from fastapi import APIRouter, Depends, HTTPException, Query, Body
from typing import List, Optional
from datetime import datetime
import logging
from src.utils.utils import get_current_user
from src.services.moohero_service import MooHeroAPIError, moohero_service
from src.utils.db import PGDB
from src.api.base_models import AnimalCreate

moohero_router = APIRouter()
logger = logging.getLogger(__name__)
db = PGDB()


@moohero_router.get(
    "/moohero/farms",
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "farms": [
                            {"moohero_id": 42, "farm_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                             "name": "Greenfield Farm"},
                            {"moohero_id": 43, "farm_id": None, "name": "Unlinked Farm"},
                        ]
                    }
                }
            }
        }
    },
)
async def list_moohero_farms(current_user: dict = Depends(get_current_user)):
    """List all farms available in MooHero, annotated with local farm links.

    `farm_id` in each result is the local farm UUID if that MooHero farm has been
    linked; `null` otherwise. Use `POST /moohero/farm-links` to establish the link.
    Returns 502 if MooHero credentials (MOOHERO_CLIENT_ID/SECRET) are invalid.
    """
    try:
        # List-only: do NOT create local farms here. Farms are owned by Farm
        # Calendar (the central system of record); the MooHero <-> local-farm
        # link is established explicitly in Setup (Thread C, via
        # moohero_farm_mapping), which is what populates `farm_id` below.
        farms = moohero_service.get_farms()
        links = db.get_moohero_farm_links()
        farms_with_links = [
            {
                'moohero_id': farm['id'],
                'farm_id': links.get(farm['id']),
                'name': farm['name'],
            }
            for farm in farms
        ]
        return {"farms": farms_with_links}
    except MooHeroAPIError:
        raise HTTPException(
            status_code=502,
            detail="MooHero rejected the configured credentials. Check MOOHERO_CLIENT_ID and MOOHERO_CLIENT_SECRET."
        )
    except Exception as e:
        logger.exception("Failed to fetch MooHero farms")
        raise HTTPException(status_code=500, detail=f"Failed to fetch MooHero farms: {str(e)}")


@moohero_router.get("/moohero/farms/{farm_id}/animals")
async def get_farm_animals(
    farm_id: int,
    current_user: dict = Depends(get_current_user)
):
    """Return all animals (collars) in a MooHero farm, fetched live from the MooHero API."""
    try:
        farm_details = moohero_service.get_farm_with_animals(farm_id)
        animals = farm_details.get('collars', [])
        return {"animals": animals, "count": len(animals)}
    except MooHeroAPIError:
        raise HTTPException(status_code=502, detail="MooHero rejected the configured credentials.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch animals: {str(e)}")


@moohero_router.get("/moohero/events")
async def get_moohero_events_from_api(
    farm_id: Optional[int] = Query(None),
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    current_user: dict = Depends(get_current_user)
):
    """Fetch MooHero health events live from the MooHero API.

    `from` and `to`: ISO 8601 date strings (e.g. `2025-06-01`).
    Use `GET /moohero/events/stored` for locally cached events.
    """
    try:
        events = moohero_service.get_events(farm_id=farm_id, from_date=from_date, to_date=to_date)
        return {"events": events, "count": len(events)}
    except MooHeroAPIError:
        raise HTTPException(status_code=502, detail="MooHero rejected the configured credentials.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch events: {str(e)}")


@moohero_router.get("/moohero/farm-mappings")
async def get_farm_mappings(current_user: dict = Depends(get_current_user)):
    """Return all MooHero → local farm mapping records."""
    try:
        mappings = db.get_moohero_farm_mappings()
        return {"mappings": mappings, "count": len(mappings)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@moohero_router.post("/moohero/farm-links")
async def link_moohero_farm(
    moohero_farm_id: int = Body(...),
    farm_id: str = Body(...),
    moohero_farm_name: Optional[str] = Body(None),
    current_user: dict = Depends(get_current_user),
):
    """Link a MooHero farm to a local (Farm Calendar) farm.

    Establishes the explicit MooHero<->farm connection that replaces the old
    name-based farm minting: it activates per-farm MooHero event scoping and
    makes the farm's moohero_id available on /farms.
    """
    try:
        result = db.upsert_moohero_farm_link(
            moohero_farm_id=moohero_farm_id,
            farm_id=farm_id,
            moohero_farm_name=moohero_farm_name,
        )
        return {"message": "MooHero farm linked", "link": result}
    except Exception as e:
        logger.exception("Failed to link MooHero farm")
        raise HTTPException(status_code=500, detail=f"Failed to link MooHero farm: {str(e)}")


@moohero_router.delete("/moohero/farm-links/{moohero_farm_id}")
async def unlink_moohero_farm(
    moohero_farm_id: int,
    current_user: dict = Depends(get_current_user),
):
    """Remove the link between a MooHero farm and a local farm."""
    try:
        removed = db.delete_moohero_farm_link(moohero_farm_id)
        return {"message": "MooHero farm unlinked", "removed": removed}
    except Exception as e:
        logger.exception("Failed to unlink MooHero farm")
        raise HTTPException(status_code=500, detail=str(e))


@moohero_router.get(
    "/animals/barn-stats",
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "days": 7,
                        "summary": {
                            "total_animals": 120,
                            "total_health_events": 8,
                            "total_heat_events": 3,
                            "barn_count": 2,
                        },
                        "barns": [
                            {"barn_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6", "animal_count": 60,
                             "total_health_events": 5, "total_heat_events": 2}
                        ],
                    }
                }
            }
        }
    },
)
async def get_barn_animal_stats(
    barn_id: Optional[str] = Query(None, description="Filter to a single barn"),
    days: int = Query(7, description="Number of days to count events over", ge=1, le=90),
    current_user: dict = Depends(get_current_user)
):
    """
    Returns a per-barn summary: animal count, total health events, heat events.
    Used for the top-level Animals page stats cards.
    """
    try:
        stats = db.get_barn_animal_stats(barn_id=barn_id, days=days)
        total_animals = sum(r.get("animal_count") or 0 for r in stats)
        total_health = sum(r.get("total_health_events") or 0 for r in stats)
        total_heat = sum(r.get("total_heat_events") or 0 for r in stats)
        return {
            "days": days,
            "summary": {
                "total_animals": total_animals,
                "total_health_events": total_health,
                "total_heat_events": total_heat,
                "barn_count": len(stats)
            },
            "barns": [dict(r) for r in stats]
        }
    except Exception as e:
        logger.exception("Failed to fetch barn animal stats")
        raise HTTPException(status_code=500, detail=str(e))


@moohero_router.get(
    "/animals",
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "animals": [
                            {
                                "id": "11111111-2222-3333-4444-555555555555",
                                "animal_name": "Bessie",
                                "barn_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                                "feeding_location_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
                                "moohero_collar_unique_id": "COLLAR-001",
                                "animal_type": "dairy_cow",
                                "health_events": 2,
                                "heat_events": 1,
                                "last_event_time": "2026-06-16T14:20:00Z",
                            }
                        ],
                        "count": 1,
                    }
                }
            }
        }
    },
)
async def list_animals(
    barn_id: Optional[str] = Query(None),
    feeding_location_id: Optional[str] = Query(None),
    with_events: bool = Query(False, description="Include per-animal event summary"),
    days: int = Query(7, description="Days to look back for event summary", ge=1, le=90),
    current_user: dict = Depends(get_current_user)
):
    """
    Returns the list of registered animals with their barn and feeding location.
    Pass with_events=true to include health/heat event counts per animal.
    """
    try:
        animals = db.get_animals(barn_id=barn_id, feeding_location_id=feeding_location_id)
        animal_list = [dict(a) for a in animals]

        if with_events and animal_list:
            animal_ids = [str(a["id"]) for a in animal_list if a.get("id")]
            event_summary = db.get_animal_event_summary(animal_ids=animal_ids, days=days)
            for animal in animal_list:
                aid = str(animal["id"])
                summary = event_summary.get(aid, {})
                animal["health_events"] = summary.get("total_events") or 0
                animal["heat_events"] = summary.get("heat_events") or 0
                last_event = summary.get("last_event_time")
                animal["last_event_time"] = last_event.isoformat() if last_event else None

        return {"animals": animal_list, "count": len(animal_list)}
    except Exception as e:
        logger.exception("Failed to fetch animals")
        raise HTTPException(status_code=500, detail=str(e))


@moohero_router.post("/animals")
async def create_animal(
    payload: AnimalCreate,
    current_user: dict = Depends(get_current_user)
):
    """Register a new animal and optionally link it to a MooHero collar."""
    try:
        animal = db.create_animal(
            animal_name=payload.animal_name,
            barn_id=payload.barn_id,
            moohero_collar_unique_id=payload.moohero_collar_unique_id,
            feeding_location_id=payload.feeding_location_id,
            animal_type=payload.animal_type
        )
        return {"message": "Animal created", "animal": dict(animal)}
    except Exception as e:
        logger.exception("Failed to create animal")
        raise HTTPException(status_code=500, detail=str(e))


@moohero_router.get("/animals/{animal_id}")
async def get_animal(
    animal_id: str,
    days: int = Query(7, description="Days to look back for event history", ge=1, le=90),
    current_user: dict = Depends(get_current_user)
):
    """
    Returns a single animal with its full event history for the past N days.
    """
    try:
        animal = db.get_animal_by_id(animal_id)
        if not animal:
            raise HTTPException(status_code=404, detail="Animal not found")

        events = db.get_moohero_events(animal_id=animal_id, days=days)
        event_list = [dict(e) for e in events]

        # Serialize datetimes
        for e in event_list:
            for key in ("event_time", "created_at"):
                if isinstance(e.get(key), datetime):
                    e[key] = e[key].isoformat()

        animal_dict = dict(animal)
        for key in ("created_at", "updated_at", "last_health_update"):
            if isinstance(animal_dict.get(key), datetime):
                animal_dict[key] = animal_dict[key].isoformat()

        return {
            "animal": animal_dict,
            "event_history_days": days,
            "event_count": len(event_list),
            "events": event_list
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to fetch animal detail")
        raise HTTPException(status_code=500, detail=str(e))


@moohero_router.put("/animals/{animal_id}")
async def update_animal(
    animal_id: str,
    animal_name: Optional[str] = Body(None),
    barn_id: Optional[str] = Body(None),
    feeding_location_id: Optional[str] = Body(None),
    moohero_collar_unique_id: Optional[str] = Body(None),
    animal_type: Optional[str] = Body(None),
    current_user: dict = Depends(get_current_user)
):
    """
    Update any combination of animal fields:
    animal_name, barn_id, feeding_location_id, moohero_collar_unique_id, animal_type.
    """
    try:
        animal = db.update_animal(
            animal_id=animal_id,
            animal_name=animal_name,
            barn_id=barn_id,
            feeding_location_id=feeding_location_id,
            moohero_collar_unique_id=moohero_collar_unique_id,
            animal_type=animal_type
        )
        if not animal:
            raise HTTPException(status_code=404, detail="Animal not found or nothing to update")
        return {"message": "Animal updated", "animal": dict(animal)}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to update animal")
        raise HTTPException(status_code=500, detail=str(e))


@moohero_router.get("/moohero/events/stored")
async def get_stored_moohero_events(
    animal_id: Optional[str] = Query(None),
    event_type: Optional[str] = Query(None),
    days: int = Query(7, description="Number of days to look back"),
    current_user: dict = Depends(get_current_user)
):
    """Return MooHero health events from the local cache.

    Events are synced periodically from MooHero. Use `GET /moohero/events` for
    live data fetched directly from MooHero.
    """
    try:
        events = db.get_moohero_events(
            animal_id=animal_id,
            event_type=event_type,
            days=days
        )
        return {"events": [dict(e) for e in events], "count": len(events)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@moohero_router.get("/moohero/events/by-collars")
async def get_stored_moohero_events_by_collar_ids(
    collar_ids: List[str] = Query(
        ...,
        description="One or more collar IDs. Use repeated query params or comma-separated values."
    ),
    event_type: Optional[str] = Query(None),
    days: int = Query(7, description="Number of days to look back"),
    current_user: dict = Depends(get_current_user)
):
    """Return cached MooHero events filtered by one or more collar IDs.

    `collar_ids` can be passed as repeated query params (`?collar_ids=A&collar_ids=B`)
    or as comma-separated values (`?collar_ids=A,B`).
    """
    try:
        normalized_ids = []
        for value in collar_ids:
            if value is None:
                continue
            parts = [p.strip() for p in str(value).split(",")]
            normalized_ids.extend([p for p in parts if p])

        if not normalized_ids:
            raise HTTPException(status_code=400, detail="At least one valid collar_id is required")

        events = db.get_moohero_events_by_collars(
            collar_ids=normalized_ids,
            event_type=event_type,
            days=days
        )
        return {
            "collar_ids": normalized_ids,
            "event_type": event_type,
            "days": days,
            "events": [dict(e) for e in events],
            "count": len(events)
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@moohero_router.get("/moohero/alerts")
async def get_moohero_alerts(
    animal_id: Optional[str] = Query(None),
    barn_id: Optional[str] = Query(None),
    feeding_location_id: Optional[str] = Query(None),
    days: int = Query(7, description="Number of days to look back"),
    current_user: dict = Depends(get_current_user)
):
    """Return MooHero health alerts, scoped to an animal, barn, or feeding location.

    If `animal_id` is provided, fetches that animal's alerts live from MooHero.
    Otherwise aggregates alerts across the specified barn or location scope.
    """
    try:
        if animal_id:
            alerts = moohero_service.get_animal_alerts(animal_id, days)
        else:
            alerts = moohero_service.get_health_alerts(
                barn_id=barn_id,
                feeding_location_id=feeding_location_id,
                days=days
            )
        return {"alerts": alerts, "count": len(alerts)}
    except MooHeroAPIError:
        raise HTTPException(status_code=502, detail="MooHero rejected the configured credentials.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
