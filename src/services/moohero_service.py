import os
import logging
import requests
from typing import List, Dict, Optional
from datetime import datetime
from src.services.moohero_oauth import MooHeroOAuth
from src.utils.db import PGDB

logger = logging.getLogger(__name__)


class MooHeroAPIError(Exception):
    pass


class MooHeroService:
    def __init__(self):
        self.base_url = "https://app.moohero.com/api"
        self.client_id = os.getenv("MOOHERO_CLIENT_ID")
        self.client_secret = os.getenv("MOOHERO_CLIENT_SECRET")
        self.enabled = bool(self.client_id and self.client_secret)
        if self.enabled:
            self.oauth = MooHeroOAuth()
        else:
            self.oauth = None
            logger.warning("MooHero credentials not configured; service disabled")
        self.db = PGDB()
    
    def _make_request(self, endpoint: str, method: str = 'GET', params: dict = None, json_data: dict = None):
        if not self.enabled:
            raise MooHeroAPIError("MooHero service is not configured")
        try:
            token = self.oauth.get_access_token()
        except Exception as e:
            logger.error(f"MooHero OAuth token acquisition failed: {e}")
            raise MooHeroAPIError(str(e)) from e

        headers = {
            'Authorization': f'Bearer {token}',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) InokronBackend/1.0'
        }
        url = f"{self.base_url}/{endpoint}"
        
        try:
            response = requests.request(method, url, headers=headers, params=params, json=json_data, timeout=30)
            response.raise_for_status()
            return response.json()
        except (requests.exceptions.RequestException, ValueError) as e:
            logger.error(f"MooHero API request failed: {endpoint} - {e}")
            raise MooHeroAPIError(str(e)) from e
    
    def get_farms(self) -> List[Dict]:
        return self._make_request('farms')
    
    def get_farm_details(self, farm_id: int) -> Dict:
        return self._make_request(f'farms/{farm_id}')
    
    def search_collar(self, unique_id: str) -> Optional[Dict]:
        result = self._make_request('collars/search', params={'unique_id': unique_id})
        return result if result else None
    
    def get_farm_with_animals(self, farm_id: int) -> Dict:
        farm_details = self._make_request(f'farms/{farm_id}')
        return farm_details
    
    def get_all_animals_from_farms(self) -> List[Dict]:
        farms = self.get_farms()
        logger.info(f"DEBUG: get_farms returned {len(farms)} farms.")
        all_animals = []
        
        for farm in farms:
            farm_details = self.get_farm_with_animals(farm['id'])
            logger.info(f"DEBUG: farm_details keys: {list(farm_details.keys())}")
            
            # They might have renamed 'collars' to 'animals' or 'devices'
            collars_list = farm_details.get('collars') or farm_details.get('animals') or farm_details.get('devices') or []
            if collars_list:
                for collar in collars_list:
                    collar['farm_id'] = farm['id']
                    collar['farm_name'] = farm.get('name')
                    all_animals.append(collar)
        
        return all_animals
    
    def get_events(self, farm_id: int = None, from_date: str = None, to_date: str = None) -> List[Dict]:
        params = {}
        if farm_id:
            params['farm_id'] = farm_id
        if from_date:
            params['from'] = from_date
        if to_date:
            params['to'] = to_date
        
        return self._make_request('events', params=params)

    def get_animal_alerts(self, animal_id: str, days: int = 7) -> List[Dict]:
        return self.db.get_animal_alerts(animal_id, days)

    def get_health_alerts(
        self,
        barn_id: str = None,
        feeding_location_id: str = None,
        days: int = 7
    ) -> List[Dict]:
        alerts = self.db.get_alerts(
            barn_id=barn_id,
            feeding_location_id=feeding_location_id,
            status=None,
            limit=500,
            offset=0
        )
        cutoff = datetime.utcnow().timestamp() - (days * 86400)
        result = []
        for alert in alerts:
            created_at = alert.get("created_at")
            if created_at and created_at.timestamp() < cutoff:
                continue
            # The old per-event animal_health + two health_spike_* alerts were
            # unified into a single rate-based `health_spike` rule.
            if alert.get("alert_type") == "health_spike":
                result.append(alert)
        return result


moohero_service = MooHeroService()
