import os
import time
import logging
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)


class MooHeroOAuth:
    def __init__(self):
        self.token_url = "https://app.moohero.com/oauth/token"
        self.client_id = os.getenv("MOOHERO_CLIENT_ID")
        self.client_secret = os.getenv("MOOHERO_CLIENT_SECRET")
        self.access_token = None
        self.token_expires_at = None
        
        if not self.client_id or not self.client_secret:
            raise ValueError("MOOHERO_CLIENT_ID and MOOHERO_CLIENT_SECRET must be set")
    
    def get_access_token(self):
        if self.access_token and self.token_expires_at > datetime.now():
            return self.access_token
        
        return self._request_new_token()
    
    def _request_new_token(self):
        try:
            response = requests.post(
                self.token_url,
                data={
                    'grant_type': 'client_credentials',
                    'client_id': self.client_id,
                    'client_secret': self.client_secret
                },
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) InokronBackend/1.0'},
                timeout=10
            )
            
            if response.status_code == 200:
                token_data = response.json()
                self.access_token = token_data['access_token']
                expires_in = token_data.get('expires_in', 3600)
                self.token_expires_at = datetime.now() + timedelta(seconds=expires_in - 300)
                logger.info("MooHero OAuth token acquired successfully")
                return self.access_token
            else:
                logger.error(f"OAuth token request failed: {response.status_code} - {response.text}")
                raise Exception(f"OAuth token request failed: {response.text}")
        except requests.exceptions.RequestException as e:
            logger.error(f"OAuth request failed: {e}")
            raise
