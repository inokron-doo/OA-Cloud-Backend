import os
import logging
import traceback
from datetime import datetime
from typing import Optional, List

import httpx
from fastapi import APIRouter, HTTPException, Depends, Request, Query
from fastapi.responses import HTMLResponse, Response
from src.utils.db import PGDB
from src.utils.utils import get_current_user
from src.utils.jwt_utils import create_access_token
from src.api.base_models import CalendarActivityCreate, CalendarActivitiesBulkCreate, ActivityTypeCreate

router = APIRouter()
db = PGDB()
logger = logging.getLogger(__name__)

FARM_CALENDAR_URL = os.getenv("FARM_CALENDAR_URL", "http://localhost:8002").rstrip('/')



@router.post("/activities")
async def create_calendar_activities(
    activities: CalendarActivityCreate | List[CalendarActivityCreate],
    current_user: dict = Depends(get_current_user)
):
    """Create one or more calendar activities.

    Accepts a single activity object or a JSON array.
    `activity_type_id` must be a valid UUID from `GET /activity-types`.
    If `end_datetime` is omitted, it defaults to `start_datetime + 1 hour`.
    """
    try:
        if isinstance(activities, list):
            activities_list = [activity.dict() for activity in activities]
        else:
            activities_list = [activities.dict()]
        
        for activity in activities_list:
            if activity.get('parent_activity_id') == '':
                activity['parent_activity_id'] = None
            if activity.get('parcel_id') == '':
                activity['parcel_id'] = None
            if activity.get('details') == '':
                activity['details'] = None
            if activity.get('responsible_agent') == '':
                activity['responsible_agent'] = None
            
            if not activity.get('end_datetime'):
                from datetime import timedelta
                activity['end_datetime'] = activity['start_datetime'] + timedelta(hours=1)
        
        import uuid
        for activity in activities_list:
            try:
                uuid.UUID(activity['activity_type_id'])
            except (ValueError, AttributeError, TypeError):
                raise HTTPException(
                    status_code=400, 
                    detail=f"Invalid activity_type_id: '{activity.get('activity_type_id')}'. Must be a valid UUID."
                )
            
            if activity.get('parent_activity_id'):
                try:
                    uuid.UUID(activity['parent_activity_id'])
                except (ValueError, AttributeError, TypeError):
                    raise HTTPException(
                        status_code=400,
                        detail=f"Invalid parent_activity_id: '{activity.get('parent_activity_id')}'. Must be a valid UUID or null."
                    )
            
            if activity.get('parcel_id'):
                try:
                    uuid.UUID(activity['parcel_id'])
                except (ValueError, AttributeError, TypeError):
                    raise HTTPException(
                        status_code=400,
                        detail=f"Invalid parcel_id: '{activity.get('parcel_id')}'. Must be a valid UUID or null."
                    )
        
        created = db.create_calendar_activities(activities_list)
        return {
            "message": f"Created {len(created)} activity(ies)",
            "activities": created
        }
    except HTTPException:
        raise
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Failed to create calendar activities")


@router.get(
    "/activities",
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "activities": [
                            {
                                "id": "act-1",
                                "title": "Morning feeding (25 kg)",
                                "start_datetime": "2026-06-18T07:00:00Z",
                                "end_datetime": "2026-06-18T08:00:00Z",
                                "activity_type_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                                "details": "Silage mix, north trough",
                            }
                        ],
                        "count": 1,
                    }
                }
            }
        }
    },
)
async def get_calendar_activities(
    parcel_id: Optional[str] = Query(None),
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    activity_type_id: Optional[str] = Query(None),
    current_user: dict = Depends(get_current_user)
):
    """List calendar activities with optional date-range and type filters."""
    try:
        activities = db.get_calendar_activities(
            parcel_id=parcel_id,
            start_date=start_date,
            end_date=end_date,
            activity_type_id=activity_type_id
        )
        return {
            "activities": activities,
            "count": len(activities)
        }
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Failed to get calendar activities")


@router.delete("/activities/{activity_id}")
async def delete_calendar_activity(
    activity_id: str,
    current_user: dict = Depends(get_current_user)
):
    """Delete a calendar activity by ID. Returns 404 if not found."""
    try:
        deleted = db.delete_calendar_activity(activity_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Activity not found")
        return {"message": "Activity deleted successfully"}
    except HTTPException:
        raise
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Failed to delete calendar activity")


@router.post("/activity-types")
async def create_activity_type(
    payload: ActivityTypeCreate,
    current_user: dict = Depends(get_current_user)
):
    """Create a new calendar activity type with display colours and category."""
    try:
        result = db.create_activity_type(
            name=payload.name,
            description=payload.description,
            background_color=payload.background_color,
            border_color=payload.border_color,
            text_color=payload.text_color,
            category=payload.category
        )
        return {
            "message": f"Activity type '{payload.name}' created successfully",
            "activity_type": result
        }
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Failed to create activity type")

@router.get(
    "/activity-types",
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "activity_type_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                        "name": "Feeding",
                    }
                }
            }
        }
    },
)
async def get_activity_types(current_user: dict = Depends(get_current_user)):
    """Return the UUID and name of the 'Feeding' activity type.

    The Feeding type UUID is required when creating feeding schedule entries
    via `POST /activities`. Currently returns only the Feeding type.
    """
    try:
        activity_types = db.get_calendar_activity_types()
        feeding_type = next((t for t in activity_types if t.get('name') == 'Feeding'), None)
        
        if not feeding_type:
            raise HTTPException(status_code=404, detail="Feeding activity type not found")
        
        return {
            "activity_type_id": feeding_type['id'],
            "name": feeding_type['name']
        }
    except HTTPException:
        raise
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Failed to fetch activity types")


@router.get("/", response_class=HTMLResponse)
async def farm_calendar_sso(current_user: dict = Depends(get_current_user)):
    """SSO redirect to the Farm Calendar application.

    Mints a short-lived Farm Calendar JWT and serves an HTML page that immediately
    redirects the browser to Farm Calendar's `/post_auth` endpoint. Intended for
    browser navigation, not API clients.
    """
    try:
        user = db.get_user_by_id(current_user["id"])
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        jwt_token = create_access_token(
            {
                "user_id": current_user["id"],
                "username": user["username"]
            },
            for_farm_calendar=True
        )
        
        html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Opening Farm Calendar</title>
    <style>
        body {{
            font-family: system-ui, -apple-system, sans-serif;
            display: flex;
            align-items: center;
            justify-content: center;
            height: 100vh;
            margin: 0;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        }}
        .card {{
            background: white;
            padding: 40px;
            border-radius: 10px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.1);
            text-align: center;
        }}
        .spinner {{
            border: 4px solid #f3f3f3;
            border-top: 4px solid #667eea;
            border-radius: 50%;
            width: 50px;
            height: 50px;
            animation: spin 1s linear infinite;
            margin: 20px auto;
        }}
        @keyframes spin {{
            0% {{ transform: rotate(0deg); }}
            100% {{ transform: rotate(360deg); }}
        }}
    </style>
</head>
<body>
    <div class="card">
        <div class="spinner"></div>
        <h2>Opening Farm Calendar</h2>
        <p>Authenticating as {user["username"]}</p>
    </div>
    <script>
        const params = new URLSearchParams({{'access_token': "{jwt_token}"}});
        const targetUrl = "{FARM_CALENDAR_URL}/post_auth?" + params.toString();
        setTimeout(function() {{
            window.location.href = targetUrl;
        }}, 500);
    </script>
</body>
</html>"""
        
        return HTMLResponse(content=html_content)
        
    except Exception as e:
        logger.error(f"SSO failed: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="SSO failed")


@router.get("/calendar")
async def calendar_view(request: Request, current_user: dict = Depends(get_current_user)):
    """Proxy the Farm Calendar main page to the authenticated browser session."""
    try:
        user = db.get_user_by_id(current_user["id"])
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        jwt_token = create_access_token(
            {
                "user_id": current_user["id"],
                "username": user["username"]
            },
            for_farm_calendar=True
        )
        
        headers = dict(request.headers)
        headers.pop("authorization", None)
        headers.pop("host", None)
        
        cookies = dict(request.cookies)
        cookies["OpenAgriAuth"] = jwt_token
        
        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
            response = await client.get(
                FARM_CALENDAR_URL,
                headers=headers,
                cookies=cookies
            )
        
        return Response(
            content=response.content,
            status_code=response.status_code,
            headers=dict(response.headers),
            media_type=response.headers.get("content-type")
        )
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Calendar view failed")

