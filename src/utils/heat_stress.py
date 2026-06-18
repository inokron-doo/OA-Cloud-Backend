"""
Heat Stress Prediction Service

This service provides simple threshold-based predictions for heat stress impacts
on cattle based on Temperature-Humidity Index (THI) values.

THI Calculation: THI = T - (0.55 - 0.0055 * RH) * (T - 58)
where T is temperature in Fahrenheit and RH is relative humidity percentage.

Heat Stress Thresholds:
- THI < 68: Normal - No heat stress
- THI 68-72: Mild - Slight decrease in feed intake and milk production
- THI 72-78: Moderate - Noticeable decrease in performance
- THI 78-84: Severe - Significant impact on health and productivity
- THI > 84: Emergency - Life-threatening conditions

Feed Drop Predictions (R1):
- THI > 78 for 4+ hours: 15-25% feed intake reduction
- THI > 84 for 4+ hours: 25-40% feed intake reduction

Severe Heat Stress Predictions (R2):
- THI > 84 for 6+ consecutive hours: Severe heat stress event predicted
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional
import logging

from src.utils.db import PGDB

logger = logging.getLogger(__name__)

db = PGDB()


def calculate_thi_fahrenheit(temp_f: float, humidity: float) -> float:
    """
    Calculate Temperature-Humidity Index using temperature in Fahrenheit.
    
    Formula: THI = T - (0.55 - 0.0055 * RH) * (T - 58)
    where T is temperature in Fahrenheit and RH is relative humidity percentage.
    """
    if temp_f is None or humidity is None:
        return None
    
    thi = temp_f - (0.55 - 0.0055 * humidity) * (temp_f - 58)
    return round(thi, 2)


def calculate_thi_celsius(temp_c: float, humidity: float) -> float:
    """
    Calculate Temperature-Humidity Index using temperature in Celsius.
    Converts to Fahrenheit first, then applies the THI formula.
    """
    if temp_c is None or humidity is None:
        return None
    
    temp_f = (temp_c * 9/5) + 32
    return calculate_thi_fahrenheit(temp_f, humidity)


def get_heat_stress_level(thi: float) -> Dict:
    """
    Determine heat stress level based on THI value.
    
    Returns dictionary with severity, description, and recommended actions.
    """
    if thi is None:
        return {
            "severity": "unknown",
            "description": "Unable to determine heat stress level",
            "thi": None
        }
    
    if thi < 68:
        return {
            "severity": "normal",
            "description": "No heat stress",
            "thi": thi,
            "color": "green"
        }
    elif thi < 72:
        return {
            "severity": "mild",
            "description": "Slight decrease in feed intake and milk production",
            "thi": thi,
            "color": "yellow"
        }
    elif thi < 78:
        return {
            "severity": "moderate",
            "description": "Noticeable decrease in performance",
            "thi": thi,
            "color": "orange"
        }
    elif thi < 84:
        return {
            "severity": "severe",
            "description": "Significant impact on health and productivity",
            "thi": thi,
            "color": "red"
        }
    else:
        return {
            "severity": "emergency",
            "description": "Life-threatening conditions",
            "thi": thi,
            "color": "darkred"
        }


def count_consecutive_hours_above_threshold(forecast_data: List[Dict], threshold: float) -> int:
    """
    Count maximum consecutive time above threshold.
    Handles forecast data with irregular intervals by calculating actual time duration.
    
    Args:
        forecast_data: List of forecast points sorted by forecast_for timestamp
        threshold: THI threshold to check against
        
    Returns:
        Maximum consecutive hours above threshold
    """
    if not forecast_data or len(forecast_data) < 2:
        return 0
    
    from datetime import datetime
    
    max_consecutive_hours = 0
    current_start = None
    
    for i, point in enumerate(forecast_data):
        thi = point.get('thi')
        forecast_time = point.get('forecast_for')
        
        if thi is None or forecast_time is None:
            current_start = None
            continue
        
        # Convert string to datetime if needed
        if isinstance(forecast_time, str):
            try:
                forecast_time = datetime.fromisoformat(forecast_time.replace('Z', '+00:00'))
            except:
                current_start = None
                continue
        
        if thi > threshold:
            if current_start is None:
                current_start = forecast_time
            
            # Calculate duration from start to current point
            duration_hours = (forecast_time - current_start).total_seconds() / 3600
            max_consecutive_hours = max(max_consecutive_hours, duration_hours)
        else:
            current_start = None
    
    return int(max_consecutive_hours)


def analyze_feeding_drop_risk(barn_id: str, hours_ahead: int = 48) -> Dict:
    """
    R1: Predict feed intake reduction based on forecasted heat stress.
    
    Predictions:
    - THI > 78 for 4+ hours: 15-25% feed intake reduction
    - THI > 84 for 4+ hours: 25-40% feed intake reduction
    
    Returns prediction with risk level, expected drop percentage, and timing.
    """
    try:
        # Get forecast data for the barn
        forecast_data = db.get_weather_forecast(barn_id, hours=hours_ahead)
        
        if not forecast_data:
            return {
                "barn_id": barn_id,
                "risk_level": "unknown",
                "message": "No forecast data available",
                "expected_feed_drop_percent": 0,
                "hours_analyzed": hours_ahead
            }
        
        # Count consecutive hours above each threshold
        hours_above_78 = count_consecutive_hours_above_threshold(forecast_data, 78)
        hours_above_84 = count_consecutive_hours_above_threshold(forecast_data, 84)
        
        # Determine risk level and expected feed drop
        if hours_above_84 >= 4:
            return {
                "barn_id": barn_id,
                "risk_level": "severe",
                "message": f"THI > 84 predicted for {hours_above_84} consecutive hours",
                "expected_feed_drop_percent_min": 25,
                "expected_feed_drop_percent_max": 40,
                "hours_analyzed": hours_ahead,
                "consecutive_hours_above_84": hours_above_84,
                "recommendation": "Immediate cooling measures required. Increase water availability, enhance ventilation, consider feed timing adjustments."
            }
        elif hours_above_78 >= 4:
            return {
                "barn_id": barn_id,
                "risk_level": "moderate",
                "message": f"THI > 78 predicted for {hours_above_78} consecutive hours",
                "expected_feed_drop_percent_min": 15,
                "expected_feed_drop_percent_max": 25,
                "hours_analyzed": hours_ahead,
                "consecutive_hours_above_78": hours_above_78,
                "recommendation": "Implement cooling strategies. Monitor feed intake closely, ensure adequate water supply."
            }
        else:
            return {
                "barn_id": barn_id,
                "risk_level": "low",
                "message": "No significant heat stress predicted",
                "expected_feed_drop_percent": 0,
                "hours_analyzed": hours_ahead,
                "recommendation": "Continue normal operations. Monitor weather updates."
            }
    
    except Exception as e:
        logger.error(f"Error analyzing feeding drop risk for barn {barn_id}: {e}")
        return {
            "barn_id": barn_id,
            "risk_level": "error",
            "message": f"Error analyzing feed drop risk: {str(e)}",
            "hours_analyzed": hours_ahead
        }


def predict_severe_heat_stress(barn_id: str, hours_ahead: int = 120) -> Dict:
    """
    R2: Predict severe heat stress events (THI > 84 for 6+ consecutive hours).
    
    Analyzes up to 5 days (120 hours) of forecast data to predict severe heat stress.
    Returns timing, duration, and peak THI of predicted events.
    """
    try:
        # Get 5-day forecast data
        forecast_data = db.get_weather_forecast(barn_id, hours=hours_ahead)
        
        if not forecast_data:
            return {
                "barn_id": barn_id,
                "severe_event_predicted": False,
                "message": "No forecast data available",
                "hours_analyzed": hours_ahead
            }
        
        # Find severe heat stress events (THI > 84 for 6+ consecutive hours)
        severe_events = []
        current_event = None
        
        for point in forecast_data:
            thi = point.get('thi')
            forecast_for = point.get('forecast_for')
            
            if thi is not None and thi > 84:
                if current_event is None:
                    current_event = {
                        "start_time": forecast_for,
                        "end_time": forecast_for,
                        "duration_hours": 1,
                        "peak_thi": thi,
                        "avg_thi": thi,
                        "thi_values": [thi]
                    }
                else:
                    current_event["end_time"] = forecast_for
                    current_event["duration_hours"] += 1
                    current_event["peak_thi"] = max(current_event["peak_thi"], thi)
                    current_event["thi_values"].append(thi)
            else:
                if current_event and current_event["duration_hours"] >= 6:
                    current_event["avg_thi"] = round(sum(current_event["thi_values"]) / len(current_event["thi_values"]), 2)
                    del current_event["thi_values"]  # Remove raw values from response
                    severe_events.append(current_event)
                current_event = None
        
        # Check if last event qualifies
        if current_event and current_event["duration_hours"] >= 6:
            current_event["avg_thi"] = round(sum(current_event["thi_values"]) / len(current_event["thi_values"]), 2)
            del current_event["thi_values"]
            severe_events.append(current_event)
        
        if severe_events:
            # Find the most severe event
            most_severe = max(severe_events, key=lambda x: x["duration_hours"])
            
            return {
                "barn_id": barn_id,
                "severe_event_predicted": True,
                "message": f"{len(severe_events)} severe heat stress event(s) predicted in next {hours_ahead} hours",
                "event_count": len(severe_events),
                "most_severe_event": most_severe,
                "all_events": severe_events,
                "hours_analyzed": hours_ahead,
                "recommendation": "Critical: Prepare emergency cooling measures. Increase monitoring frequency. Ensure veterinary support is available."
            }
        else:
            return {
                "barn_id": barn_id,
                "severe_event_predicted": False,
                "message": "No severe heat stress events predicted (THI > 84 for 6+ hours)",
                "hours_analyzed": hours_ahead
            }
    
    except Exception as e:
        logger.error(f"Error predicting severe heat stress for barn {barn_id}: {e}")
        return {
            "barn_id": barn_id,
            "severe_event_predicted": False,
            "message": f"Error predicting heat stress: {str(e)}",
            "hours_analyzed": hours_ahead
        }


def get_current_heat_stress_status(barn_id: str) -> Dict:
    """
    R3: Get current heat stress status with edge parameters for alarm triggering.
    
    Returns current THI, stress level, and boolean flags for different severity thresholds
    that can be used to trigger edge device alarms.
    """
    try:
        # Get current weather with THI
        current_weather = db.get_current_weather_with_thi(barn_id)
        
        if not current_weather:
            return {
                "barn_id": barn_id,
                "status": "no_data",
                "message": "No current weather data available",
                "edge_parameters": {
                    "alarm_mild": False,
                    "alarm_moderate": False,
                    "alarm_severe": False,
                    "alarm_emergency": False
                }
            }
        
        thi = current_weather.get('thi')
        temperature = current_weather.get('temperature')
        humidity = current_weather.get('humidity')
        obs_time = current_weather.get('obs_time')
        
        # Get heat stress level
        stress_level = get_heat_stress_level(thi)
        
        # Generate edge parameters (boolean flags for each threshold)
        edge_parameters = {
            "alarm_mild": thi >= 68 if thi is not None else False,
            "alarm_moderate": thi >= 72 if thi is not None else False,
            "alarm_severe": thi >= 78 if thi is not None else False,
            "alarm_emergency": thi >= 84 if thi is not None else False,
            "thi_value": thi,
            "timestamp": obs_time
        }
        
        return {
            "barn_id": barn_id,
            "status": stress_level["severity"],
            "current_thi": thi,
            "temperature_c": temperature,
            "humidity_percent": humidity,
            "observation_time": obs_time,
            "stress_level": stress_level,
            "edge_parameters": edge_parameters,
            "recommendation": _get_current_recommendation(stress_level["severity"])
        }
    
    except Exception as e:
        logger.error(f"Error getting current heat stress status for barn {barn_id}: {e}")
        return {
            "barn_id": barn_id,
            "status": "error",
            "message": f"Error retrieving heat stress status: {str(e)}",
            "edge_parameters": {
                "alarm_mild": False,
                "alarm_moderate": False,
                "alarm_severe": False,
                "alarm_emergency": False
            }
        }


def _get_current_recommendation(severity: str) -> str:
    """Get recommendation based on current heat stress severity."""
    recommendations = {
        "normal": "No action required. Continue normal operations.",
        "mild": "Monitor animals. Ensure adequate water supply and ventilation.",
        "moderate": "Activate cooling systems. Increase water availability. Monitor feed intake.",
        "severe": "Emergency cooling required. Adjust feeding schedule. Increase monitoring frequency.",
        "emergency": "Critical situation. Maximum cooling measures. Consider veterinary intervention. Move animals if possible."
    }
    return recommendations.get(severity, "Monitor conditions closely.")
