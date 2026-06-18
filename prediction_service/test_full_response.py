import os
import json

os.environ["DATABASE_URL"] = "postgresql://inokron_user:Inokron123@72.146.216.68:5433/inokron_db"

from app.services.data_loader import load_prediction_input
from app.services.settings_service import resolve_prediction_settings
from app.services.forecast_engine import generate_feed_forecast
from datetime import datetime

fid = "8cf4bb2b-7e41-443a-bf01-23689f72a2ae"
bid = "1c92e7b6-925a-4cec-8a39-7468c1e6093f"
settings = resolve_prediction_settings(barn_id=bid, feeding_location_id=fid)
data = load_prediction_input(
    feeding_location_id=fid,
    history_hours=int(settings["prediction_history_hours"]),
    forecast_hours=int(settings["prediction_forecast_hours"]),
)
result = generate_feed_forecast(
    history=data["history"],
    feeding_events=data["feeding_events"],
    settings=settings,
)

response = {
    "status": result.get("status", "unknown"),
    "feeding_location_id": fid,
    "barn_id": bid,
    "generated_at": datetime.utcnow().isoformat() + "Z",
    "result": result,
    "settings_used": settings,
    "unmapped_events": [],
}

print(json.dumps(response, indent=2, default=str))
