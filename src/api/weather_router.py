import os
import logging
from datetime import datetime, timedelta
import traceback
import httpx
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Query, Body, Request

from src.utils.utils import get_current_user
from src.utils.db import PGDB
from src.services.weather_scheduler import weather_scheduler
from src.utils import heat_stress

db = PGDB()
weather_router = APIRouter()
logger = logging.getLogger(__name__)

WEATHER_SERVICE_URL = os.getenv("WEATHER_SERVICE_URL", "http://127.0.0.1:8004")
WEATHER_SERVICE_USERNAME = os.getenv("WEATHER_SERVICE_USERNAME", "test")
WEATHER_SERVICE_PASSWORD = os.getenv("WEATHER_SERVICE_PASSWORD", "test")

_weather_token = None
_weather_token_expiry = None

async def get_weather_token():
    global _weather_token, _weather_token_expiry
    if _weather_token and _weather_token_expiry > datetime.utcnow():
        return _weather_token

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{WEATHER_SERVICE_URL}/api/v1/auth/token",
            data={
                "grant_type": "",
                "username": WEATHER_SERVICE_USERNAME,
                "password": WEATHER_SERVICE_PASSWORD,
                "scope": "",
                "client_id": "",
                "client_secret": "",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if response.status_code != 200:
            raise HTTPException(status_code=500, detail="Failed to get weather service token")
        data = response.json()
        _weather_token = data["jwt_token"]
        _weather_token_expiry = datetime.utcnow() + timedelta(minutes=240)
        return _weather_token

@weather_router.get(
    "/weather/current/",
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "lat": 48.21,
                        "lon": 16.37,
                        "obs_time": "2026-06-17T09:00:00Z",
                        "temperature": 28.4,
                        "humidity": 55.0,
                        "thi": 76.2,
                    }
                }
            }
        }
    },
)
async def get_current_weather(
    request: Request,
    lat: float = Query(...),
    lon: float = Query(...),
    current_user: dict = Depends(get_current_user),
):
    """Return the current weather observation for a given lat/lon.

    Fetches from the weather service, computes THI (Temperature-Humidity Index),
    saves the result to the DB, and returns the combined observation.
    Supports JSON-LD via `Accept: application/ld+json`.
    """
    try:
        token = await get_weather_token()
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{WEATHER_SERVICE_URL}/api/data/weather/?lat={lat}&lon={lon}",
                headers={"Authorization": f"Bearer {token}"},
            )
            if response.status_code != 200:
                raise HTTPException(status_code=response.status_code, detail="Weather service error")
            
            data = response.json()
            
            temperature = None
            humidity = None
            obs_time = None
            
            if isinstance(data, list) and len(data) > 0:
                for item in data:
                    if item.get('measurement_type') == 'ambient_temperature':
                        temperature = item.get('value')
                        obs_time = item.get('timestamp')
                    elif item.get('measurement_type') == 'ambient_humidity':
                        humidity = item.get('value')
            elif isinstance(data, dict):
                main_data = data.get('data', {}).get('main', {})
                temperature = main_data.get('temp')
                humidity = main_data.get('humidity')
                dt_value = data.get('data', {}).get('dt')
                if dt_value is not None:
                    obs_time = datetime.utcfromtimestamp(dt_value).isoformat()
            
            thi = None
            if temperature is not None and humidity is not None:
                thi = heat_stress.calculate_thi_celsius(temperature, humidity)

            db.save_weather_data({
                'obs_time': obs_time,
                'lat': lat,
                'lon': lon,
                'temperature': temperature,
                'humidity': humidity,
                'thi': thi,
                'raw': data
            })
            
            plain = {
                "lat": lat,
                "lon": lon,
                "obs_time": obs_time,
                "temperature": temperature,
                "humidity": humidity,
                "thi": thi,
                "raw": data,
            }

            from src.utils.jsonld import wants_jsonld, ld_response, current_weather_to_ld
            if wants_jsonld(request):
                return ld_response([current_weather_to_ld(plain)])
            return plain

    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Failed to fetch current weather")


@weather_router.get("/weather/{barn_id}/history")
async def get_barn_weather_history(
    barn_id: str,
    request: Request,
    hours: int = Query(24, description="Hours of history", ge=1, le=168),
    start_time: datetime = Query(None, description="Optional start datetime for anchoring"),
    end_time: datetime = Query(None, description="Optional end datetime for anchoring"),
    current_user: dict = Depends(get_current_user)
):
    """Get historical weather observations from database"""
    try:
        from src.api.anchor_router import get_anchor_window
        from src.utils.jsonld import wants_jsonld, ld_response, weather_history_row_to_ld
        if start_time is None and end_time is None:
            start_time, end_time = get_anchor_window(history_hours=hours)

        history = db.get_weather_history(barn_id, hours=hours, start_time=start_time, end_time=end_time)
        if wants_jsonld(request):
            return ld_response([weather_history_row_to_ld(barn_id, row) for row in history])
        return {
            "barn_id": barn_id,
            "hours": hours,
            "data": history,
            "count": len(history)
        }
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Failed to fetch weather history")


@weather_router.get(
    "/weather/{barn_id}/forecast",
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "barn_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                        "lat": 48.21,
                        "lon": 16.37,
                        "hours_requested": 48,
                        "forecast_points": 1,
                        "forecast": [
                            {
                                "forecast_for": "2026-06-18T12:00:00",
                                "temperature": 31.2,
                                "humidity": 48.0,
                                "thi": 78.9,
                                "wind_speed": 3.1,
                                "precipitation": 0.0,
                            }
                        ],
                        "source": "live_api:/api/data/forecast5",
                    }
                }
            }
        }
    },
)
async def get_barn_weather_forecast(
    barn_id: str,
    request: Request,
    hours: int = Query(48, description="Hours of forecast to retrieve (max 120)", ge=1, le=120),
    current_user: dict = Depends(get_current_user),
):
    """
    Get weather forecast for a specific barn.
    Returns up to 5 days (120 hours) of hourly forecasts with THI calculations.
    
    Args:
        barn_id: Barn identifier
        hours: Number of hours of forecast (default 48, max 120)
    """
    try:
        barn = db.get_barn_by_id(barn_id)
        if not barn:
            raise HTTPException(status_code=404, detail=f"Barn not found: {barn_id}")

        lat = barn.get("latitude")
        lon = barn.get("longitude")
        if lat is None or lon is None:
            raise HTTPException(
                status_code=400,
                detail=f"Barn {barn_id} has no latitude/longitude configured"
            )

        token = await get_weather_token()
        normalized_forecast = []

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{WEATHER_SERVICE_URL}/api/data/forecast5/?lat={lat}&lon={lon}",
                headers={"Authorization": f"Bearer {token}"},
            )

        if response.status_code == 200:
            raw_items = response.json()
            if isinstance(raw_items, list):
                now_utc = datetime.utcnow()
                cutoff_utc = now_utc + timedelta(hours=hours)
                grouped = defaultdict(dict)

                for item in raw_items:
                    ts = item.get("timestamp")
                    mtype = item.get("measurement_type")
                    value = item.get("value")
                    if ts and mtype and value is not None:
                        grouped[ts][mtype] = value

                for ts, values in sorted(grouped.items(), key=lambda x: x[0]):
                    ts_clean = ts.replace("Z", "+00:00") if isinstance(ts, str) else ts
                    try:
                        ts_dt = datetime.fromisoformat(ts_clean)
                    except Exception:
                        continue

                    if ts_dt.tzinfo is not None:
                        ts_dt = ts_dt.replace(tzinfo=None)

                    if ts_dt < now_utc or ts_dt > cutoff_utc:
                        continue

                    temperature = values.get("ambient_temperature")
                    humidity = values.get("ambient_humidity")
                    thi = None
                    if temperature is not None and humidity is not None:
                        thi = heat_stress.calculate_thi_celsius(temperature, humidity)

                    normalized_forecast.append({
                        "forecast_for": ts_dt.isoformat(),
                        "temperature": temperature,
                        "humidity": humidity,
                        "thi": thi,
                        "wind_speed": values.get("wind_speed"),
                        "wind_direction": values.get("wind_direction"),
                        "precipitation": values.get("precipitation"),
                        "rainfall_3h": values.get("rainfall_3h"),
                    })

            from src.utils.jsonld import wants_jsonld, ld_response, forecast_point_to_ld
            if wants_jsonld(request):
                return ld_response([forecast_point_to_ld(barn_id, pt, "live_api:/api/data/forecast5") for pt in normalized_forecast])
            return {
                "barn_id": barn_id,
                "lat": lat,
                "lon": lon,
                "hours_requested": hours,
                "forecast_points": len(normalized_forecast),
                "forecast": normalized_forecast,
                "source": "live_api:/api/data/forecast5"
            }

        logger.error(
            "Live forecast fetch failed, using DB fallback",
            extra={"barn_id": barn_id, "status_code": response.status_code}
        )
        forecast_data = db.get_weather_forecast(barn_id, hours=hours)

        from src.utils.jsonld import wants_jsonld, ld_response, forecast_point_to_ld
        if wants_jsonld(request):
            return ld_response([forecast_point_to_ld(barn_id, pt, "db_fallback") for pt in forecast_data])
        return {
            "barn_id": barn_id,
            "lat": lat,
            "lon": lon,
            "hours_requested": hours,
            "forecast_points": len(forecast_data),
            "forecast": forecast_data,
            "source": "db_fallback"
        }
    
    except Exception as e:
        logger.exception(
            "Failed to fetch barn forecast",
            extra={"barn_id": barn_id, "hours": hours}
        )
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch barn forecast: {str(e)}"
        )



@weather_router.get(
    "/heat-stress/{barn_id}/feeding-predictions",
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "barn_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                        "risk_level": "high",
                        "expected_feed_drop_percent": 22,
                        "window": {"start": "2026-06-18T11:00:00Z", "end": "2026-06-18T17:00:00Z"},
                        "peak_thi": 85.1,
                        "recommendations": ["Shift feeding to cooler hours"],
                    }
                }
            }
        }
    },
)
async def predict_feeding_drop(
    barn_id: str,
    request: Request,
    hours_ahead: int = Query(48, description="Hours to analyze for predictions (max 120)", ge=1, le=120),
    current_user: dict = Depends(get_current_user),
):
    """
    R1: Predict feed intake reduction due to heat stress.

    DEPRECATED: superseded by the unified alert engine, which emits predicted
    heat_stress alerts (origin="predicted") via `GET /feed/alerts/new?origin=all`
    using the configurable THI thresholds. Kept for one release; do not build new
    integrations against it.

    Analyzes forecast data to predict:
    - THI > 78 for 4+ hours: 15-25% feed intake reduction
    - THI > 84 for 4+ hours: 25-40% feed intake reduction

    Returns risk level, expected feed drop percentage, and recommendations.
    """
    try:
        from src.utils.jsonld import wants_jsonld, ld_response, feeding_drop_risk_to_ld
        prediction = heat_stress.analyze_feeding_drop_risk(barn_id, hours_ahead=hours_ahead)
        if wants_jsonld(request):
            return ld_response(feeding_drop_risk_to_ld(prediction))
        return prediction

    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Failed to predict feeding drop")


@weather_router.get("/heat-stress/{barn_id}/predictions")
async def predict_severe_heat_stress(
    barn_id: str,
    request: Request,
    hours_ahead: int = Query(120, description="Hours to analyze (max 120 = 5 days)", ge=1, le=120),
    current_user: dict = Depends(get_current_user),
):
    """
    R2: Predict severe heat stress events (THI > 84 for 6+ consecutive hours).

    DEPRECATED: superseded by predicted heat_stress alerts from the unified alert
    engine (`GET /feed/alerts/new?origin=all`). Kept for one release; do not build
    new integrations against it.

    Analyzes up to 5 days of forecast data to identify periods of severe heat stress.
    Returns timing, duration, and peak THI of predicted severe events.
    """
    try:
        from src.utils.jsonld import wants_jsonld, ld_response, severe_heat_stress_to_ld
        prediction = heat_stress.predict_severe_heat_stress(barn_id, hours_ahead=hours_ahead)
        if wants_jsonld(request):
            return ld_response(severe_heat_stress_to_ld(prediction))
        return prediction

    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Failed to predict severe heat stress")


@weather_router.get(
    "/heat-stress/{barn_id}/status",
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "barn_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                        "thi": 76.2,
                        "stress_level": "moderate",
                        "edge_flags": {
                            "mild": True,
                            "moderate": True,
                            "severe": False,
                            "emergency": False,
                        },
                        "recommendations": ["Increase ventilation", "Ensure water access"],
                    }
                }
            }
        }
    },
)
async def get_current_heat_stress(
    barn_id: str,
    request: Request,
    current_user: dict = Depends(get_current_user),
):
    """
    R3: Get current heat stress status with edge parameters for alarm triggering.

    Returns:
    - Current THI value and stress level (normal, mild, moderate, severe, emergency)
    - Edge parameters: Boolean flags for each severity threshold
    - Recommendations based on current conditions

    Edge devices can use the alarm flags to trigger cooling systems automatically.
    """
    try:
        from src.utils.jsonld import wants_jsonld, ld_response, heat_stress_status_to_ld
        status = heat_stress.get_current_heat_stress_status(barn_id)
        if wants_jsonld(request):
            return ld_response(heat_stress_status_to_ld(status))
        return status

    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Failed to get heat stress status")



@weather_router.post("/weather/scheduler/start")
async def start_weather_scheduler(current_user: dict = Depends(get_current_user)):
    """
    Start automatic weather data collection.
    Weather will be fetched at configured interval.
    """
    try:
        weather_scheduler.start()
        return {
            "message": "Weather scheduler started successfully",
            "status": weather_scheduler.get_status()
        }
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to start scheduler: {str(e)}")


@weather_router.post("/weather/scheduler/stop")
async def stop_weather_scheduler(current_user: dict = Depends(get_current_user)):
    """
    Stop automatic weather data collection.
    """
    try:
        weather_scheduler.stop()
        return {
            "message": "Weather scheduler stopped successfully",
            "status": weather_scheduler.get_status()
        }
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to stop scheduler: {str(e)}")


@weather_router.post("/weather/scheduler/interval")
async def update_forecast_interval(
    interval_minutes: int = Body(..., embed=True, ge=1, le=1440),
    current_user: dict = Depends(get_current_user)
):
    """Update the automatic weather-fetch interval.

    `interval_minutes`: 1–1440 (1 minute to 24 hours). Changes take effect at the next tick.
    """
    try:
        weather_scheduler.update_interval(interval_minutes)
        return {
            "message": f"Forecast interval updated to {interval_minutes} minutes",
            "status": weather_scheduler.get_status()
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to update interval: {str(e)}")


@weather_router.get("/weather/scheduler/status")
async def get_scheduler_status(current_user: dict = Depends(get_current_user)):
    """Return the current status and configuration of the automatic weather scheduler."""
    try:
        return weather_scheduler.get_status()
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to get scheduler status: {str(e)}")


@weather_router.post("/weather/fetch-now")
async def fetch_weather_now(current_user: dict = Depends(get_current_user)):
    """Trigger an immediate weather fetch for all configured barns."""
    try:
        await weather_scheduler.fetch_all_forecasts()
        return {
            "message": "Weather forecast fetch completed successfully",
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to fetch weather: {str(e)}")



def _generate_trends_summary(trends: list) -> dict:
    """Generate summary statistics from daily trends"""
    if not trends:
        return {}
    
    temps = [t.get('avg_temperature') for t in trends if t.get('avg_temperature') is not None]
    humidities = [t.get('avg_humidity') for t in trends if t.get('avg_humidity') is not None]
    
    return {
        "temperature": {
            "overall_avg": sum(temps) / len(temps) if temps else None,
            "overall_max": max(temps) if temps else None,
            "overall_min": min(temps) if temps else None,
            "trend": "increasing" if temps and temps[0] > temps[-1] else "decreasing" if temps and temps[0] < temps[-1] else "stable"
        },
        "humidity": {
            "overall_avg": sum(humidities) / len(humidities) if humidities else None,
            "overall_max": max(humidities) if humidities else None,
            "overall_min": min(humidities) if humidities else None
        },
        "days_analyzed": len(trends)
    }