from typing import Optional

from app.config import settings


def get_internal_api_key() -> Optional[str]:
    value = settings.prediction_service_api_key
    return value or None
