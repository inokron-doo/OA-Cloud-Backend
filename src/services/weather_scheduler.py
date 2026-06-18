import os
import logging
import asyncio
import traceback
from datetime import datetime, timedelta
from typing import Dict, List
import httpx

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from src.utils.db import PGDB

logger = logging.getLogger(__name__)

WEATHER_SERVICE_URL = os.getenv("WEATHER_SERVICE_URL", "http://127.0.0.1:8010")
WEATHER_SERVICE_USERNAME = os.getenv("WEATHER_SERVICE_USERNAME", "test")
WEATHER_SERVICE_PASSWORD = os.getenv("WEATHER_SERVICE_PASSWORD", "test")

_weather_token = None
_weather_token_expiry = None


class WeatherScheduler:
    
    def __init__(self):
        self.db = PGDB()
        self.scheduler = AsyncIOScheduler()
        self.forecast_interval_minutes = int(os.getenv("FORECAST_INTERVAL_MINUTES", "720"))
        self.current_weather_interval_minutes = int(os.getenv("CURRENT_WEATHER_INTERVAL_MINUTES", "30"))
        self.forecast_job_id = "forecast_weather_job"
        self.current_weather_job_id = "current_weather_job"
        self.is_running = False
        
    async def get_weather_token(self) -> str:
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
                logger.error(f"Failed to get weather token: {response.status_code}")
                raise Exception("Failed to authenticate with weather service")
            
            data = response.json()
            _weather_token = data["jwt_token"]
            _weather_token_expiry = datetime.utcnow() + timedelta(minutes=240)
            
            return _weather_token
    
    async def fetch_forecast_for_barn(self, barn: Dict) -> None:
        try:
            lat = barn.get('latitude')
            lon = barn.get('longitude')
            
            if not lat or not lon:
                logger.warning(f"Barn {barn.get('name')} has no coordinates, skipping")
                return
            
            token = await self.get_weather_token()
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                forecast_response = await client.get(
                    f"{WEATHER_SERVICE_URL}/api/data/weather/?lat={lat}&lon={lon}",
                    headers={"Authorization": f"Bearer {token}"},
                )
                
                if forecast_response.status_code == 200:
                    forecast_data = forecast_response.json()
                    await self._save_forecast_weather(forecast_data, lat, lon, barn)
                else:
                    logger.error(f"Failed to fetch forecast for {barn.get('name')}: {forecast_response.status_code}")
                    
        except Exception as e:
            logger.error(f"Error fetching forecast for barn {barn.get('name')}: {e}")
            traceback.print_exc()
    
    async def _save_forecast_weather(self, data: List, lat: float, lon: float, barn: Dict):
        try:
            if not isinstance(data, list):
                logger.warning(f"Forecast data is not a list for barn {barn.get('name')}")
                return
            
            if not data:
                logger.warning(f"Empty forecast data for barn {barn.get('name')}")
                return
            
            import uuid
            from collections import defaultdict
            
            forecast_time = datetime.utcnow()
            batch_id = str(uuid.uuid4())
            barn_id = barn.get('id') or barn.get('barn_id')
            
            if not barn_id:
                logger.error(f"No barn_id found for barn {barn.get('name')}")
                return
            
            from src.utils.heat_stress import calculate_thi_celsius
            
            measurements_by_time = defaultdict(dict)
            
            for item in data:
                timestamp = item.get('timestamp')
                measurement_type = item.get('measurement_type')
                value = item.get('value')
                
                if timestamp and measurement_type and value is not None:
                    measurements_by_time[timestamp][measurement_type] = value
            
            saved_count = 0
            skipped_count = 0
            
            for timestamp_str, measurements in measurements_by_time.items():
                temp = measurements.get('ambient_temperature')
                hum = measurements.get('ambient_humidity')
                
                if temp is not None and hum is not None:
                    thi = calculate_thi_celsius(temp, hum)
                    
                    if thi is not None and 0 <= thi <= 150:
                        from dateutil import parser
                        forecast_for_dt = parser.parse(timestamp_str)
                        forecast_for_str = forecast_for_dt.strftime('%Y-%m-%d %H:%M:%S')
                        
                        self.db.insert_weather_forecast(
                            barn_id=barn_id,
                            batch_id=batch_id,
                            forecast_time=forecast_time,
                            forecast_for=forecast_for_str,
                            temperature=temp,
                            humidity=hum,
                            thi=round(thi, 2),
                            raw={}
                        )
                        saved_count += 1
                    else:
                        logger.warning(f"Invalid THI value: {thi}")
                        skipped_count += 1
                else:
                    skipped_count += 1
            
            logger.info(
                f"Saved {saved_count} forecast points for {barn.get('name')} "
                f"(batch_id: {batch_id}, skipped {skipped_count})"
            )
            
        except Exception as e:
            logger.error(f"Error saving forecast weather: {e}")
            traceback.print_exc()
    
    async def fetch_all_forecasts(self):
        try:
            logger.info("Fetching forecasts for all barns")
            
            barns = self.db.get_all_barns()
            if not barns:
                logger.warning("No barns found in database")
                return
            
            for barn in barns:
                await self.fetch_forecast_for_barn(barn)
            
            logger.info(f"Completed fetching forecasts for {len(barns)} barns")
            
        except Exception as e:
            logger.error(f"Error fetching all forecasts: {e}")
            traceback.print_exc()
    
    async def fetch_current_weather_for_barn(self, barn: Dict) -> None:
        try:
            lat = barn.get('latitude')
            lon = barn.get('longitude')
            barn_id = barn.get('id') or barn.get('barn_id')
            
            if not lat or not lon or not barn_id:
                return
            
            token = await self.get_weather_token()
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{WEATHER_SERVICE_URL}/api/data/weather/?lat={lat}&lon={lon}",
                    headers={"Authorization": f"Bearer {token}"},
                )
                
                if response.status_code == 200:
                    current_data = response.json()
                    await self._save_current_weather(current_data, barn_id)
                else:
                    logger.error(f"Failed to fetch current weather: {response.status_code}")
                    
        except Exception as e:
            logger.error(f"Error fetching current weather: {e}")
            traceback.print_exc()
    
    async def _save_current_weather(self, data: Dict, barn_id: str):
        try:
            from src.utils.heat_stress import calculate_thi_celsius
            
            weather_data = data.get('data', {})
            main_data = weather_data.get('main', {})
            temperature = main_data.get('temp')
            humidity = main_data.get('humidity')
            obs_time = datetime.utcnow()
            
            if temperature is None or humidity is None:
                logger.warning("Missing temperature or humidity data")
                return
            
            thi = calculate_thi_celsius(temperature, humidity)
            
            self.db.save_weather_observation(
                barn_id=barn_id,
                temperature=temperature,
                humidity=humidity,
                thi=thi,
                obs_time=obs_time
            )
            
            logger.info(f"Saved current weather: temp={temperature}°C, humidity={humidity}%, THI={thi}")
            
        except Exception as e:
            logger.error(f"Error saving current weather: {e}")
            traceback.print_exc()
    
    async def fetch_all_current_weather(self):
        try:
            logger.info("Fetching current weather for all barns")
            
            barns = self.db.get_all_barns()
            if not barns:
                return
            
            for barn in barns:
                await self.fetch_current_weather_for_barn(barn)
            
            logger.info(f"Completed fetching current weather for {len(barns)} barns")
            
        except Exception as e:
            logger.error(f"Error fetching all current weather: {e}")
            traceback.print_exc()
    
    def start(self):
        if self.is_running:
            logger.warning("Scheduler is already running")
            return
        
        self.scheduler.add_job(
            self.fetch_all_forecasts,
            trigger=IntervalTrigger(minutes=self.forecast_interval_minutes),
            id=self.forecast_job_id,
            replace_existing=True,
            max_instances=1
        )
        
        self.scheduler.add_job(
            self.fetch_all_current_weather,
            trigger=IntervalTrigger(minutes=self.current_weather_interval_minutes),
            id=self.current_weather_job_id,
            replace_existing=True,
            max_instances=1
        )
        
        self.scheduler.start()
        self.is_running = True
        logger.info(f"Weather scheduler started (forecast: {self.forecast_interval_minutes}min, current: {self.current_weather_interval_minutes}min)")
    
    def stop(self):
        if not self.is_running:
            return
        
        self.scheduler.shutdown(wait=False)
        self.is_running = False
        logger.info("Weather scheduler stopped")
    
    def update_interval(self, minutes: int):
        if minutes < 1 or minutes > 1440:
            raise ValueError("Interval must be between 1 and 1440 minutes")
        
        self.forecast_interval_minutes = minutes
        
        if self.is_running:
            self.scheduler.reschedule_job(
                self.forecast_job_id,
                trigger=IntervalTrigger(minutes=minutes)
            )
            logger.info(f"Updated forecast interval to {minutes} minutes")
    
    def get_status(self) -> Dict:
        status = {
            "is_running": self.is_running,
            "forecast_interval_minutes": self.forecast_interval_minutes,
            "current_weather_interval_minutes": self.current_weather_interval_minutes
        }
        
        if self.is_running:
            forecast_job = self.scheduler.get_job(self.forecast_job_id)
            current_job = self.scheduler.get_job(self.current_weather_job_id)
            status["forecast_next_run"] = forecast_job.next_run_time.isoformat() if forecast_job else None
            status["current_weather_next_run"] = current_job.next_run_time.isoformat() if current_job else None
        
        return status


weather_scheduler = WeatherScheduler()
