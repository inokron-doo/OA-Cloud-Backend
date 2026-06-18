import os
os.environ["DATABASE_URL"] = "postgresql://inokron_user:Inokron123@72.146.216.68:5433/inokron_db"

from app.services.data_loader import load_prediction_input
from app.services.settings_service import resolve_prediction_settings
from app.services.forecast_engine import generate_feed_forecast

feeding_location_id = "8cf4bb2b-7e41-443a-bf01-23689f72a2ae"
barn_id = "1c92e7b6-925a-4cec-8a39-7468c1e6093f"

settings = resolve_prediction_settings(
    barn_id=barn_id,
    feeding_location_id=feeding_location_id,
)

data = load_prediction_input(
    feeding_location_id=feeding_location_id,
    history_hours=int(settings["prediction_history_hours"]),
    forecast_hours=int(settings["prediction_forecast_hours"]),
)

result = generate_feed_forecast(
    history=data["history"],
    feeding_events=data["feeding_events"],
    settings=settings,
)

print("status:", result["status"])

activities = result.get("upcoming_feeding_activities", [])
print(f"\nupcoming_feeding_activities: {len(activities)}")
for a in activities:
    print(f"  {a['local_time']}  {a['quantity_kg']}kg  {a['title']}")

assert "upcoming_feeding_activities" in result
assert len(activities) > 0
print("\nUPCOMING ACTIVITIES TEST PASSED")
