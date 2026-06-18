from fastapi import APIRouter, Depends, HTTPException, Body
from datetime import datetime, time, timedelta, timezone
import traceback

from src.utils.db import PGDB
from src.utils.utils import get_current_user

router = APIRouter(prefix="/anchor-time", tags=["Settings"])
db = PGDB()


def get_anchor_window(history_hours: int = 24):
    """
    Read the saved anchor time from DB and return (start_time, end_time)
    for the current working day.

    The anchor defines when the farmer's day starts (e.g. 06:00).
    start_time = today at anchor_time (or yesterday if current time is before anchor)
    end_time   = start_time + history_hours
    Returns (None, None) if no anchor is saved.
    """
    try:
        settings = db.get_app_settings()
        raw = settings.get("day_start_anchor_time")
        if not raw:
            return None, None

        h, m, s = (int(x) for x in raw.split(":"))
        anchor = time(h, m, s)

        now = datetime.now(tz=timezone.utc)
        today_anchor = now.replace(hour=h, minute=m, second=s, microsecond=0)
        if now < today_anchor:
            today_anchor -= timedelta(days=1)

        if history_hours == 24:
            start = today_anchor
            end = start + timedelta(hours=24)
        else:
            end = today_anchor + timedelta(hours=24)
            start = end - timedelta(hours=history_hours)
            
        return start, end
    except Exception:
        return None, None


@router.get(
    "/",
    responses={
        200: {"content": {"application/json": {"example": {"anchor_time": "06:00:00"}}}}
    },
)
def get_anchor_time(current_user: dict = Depends(get_current_user)):
    """Return the configured day-start anchor time (HH:MM:SS).

    The anchor defines when the farmer's working day begins. Historical data windows
    for charts and alert analysis are computed relative to this time.
    Returns `00:00:00` if not yet configured.
    """
    try:
        settings = db.get_app_settings()
        anchor_time = settings.get("day_start_anchor_time", "00:00:00")
        return {"anchor_time": anchor_time}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/")
def update_anchor_time(
    anchor_time: str = Body(..., embed=True),
    current_user: dict = Depends(get_current_user)
):
    """Set the day-start anchor time.

    `anchor_time` format: `HH:MM` or `HH:MM:SS`. Affects the time windows used
    for feed history charts and alert analysis across all barns.
    """
    try:
        # Example validation: format should be HH:MM or HH:MM:SS
        db.set_app_setting("day_start_anchor_time", anchor_time)
        return {"message": "Anchor time updated successfully", "anchor_time": anchor_time}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
