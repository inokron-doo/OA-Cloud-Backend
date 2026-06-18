"""
OCSM / JSON-LD serialisation utilities for Inokron-backend.

Content negotiation (§1.1): JSON-LD is returned ONLY when the client sends
  Accept: application/ld+json
Any other Accept value returns plain JSON so the frontend is unaffected.

URN scheme (§1.2):
  urn:inokron:<Class>:<uuid>
  urn:inokron:Observation:<barn_id>:<kind>:<iso_time>

Feature-of-interest alignment (§1.3):
  Inokron barns ARE Farm Calendar parcels.  Their FoI URN therefore uses
  the calendar's own namespace: urn:farmcalendar:FarmParcel:<barn_id>
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

OCSM_CONTEXT = "https://w3id.org/ocsm/main-context.jsonld"
LD_CONTENT_TYPE = "application/ld+json"


# --------------------------------------------------------------------------- #
#  Content-negotiation helpers                                                  #
# --------------------------------------------------------------------------- #

def wants_jsonld(request: Request) -> bool:
    """True iff the client explicitly requested application/ld+json."""
    return LD_CONTENT_TYPE in request.headers.get("accept", "")


def ld_response(graph: list[dict]) -> JSONResponse:
    """Wrap objects in an OCSM @context + @graph envelope."""
    return JSONResponse(
        content={"@context": OCSM_CONTEXT, "@graph": graph},
        media_type=LD_CONTENT_TYPE,
    )


# --------------------------------------------------------------------------- #
#  URN minters                                                                  #
# --------------------------------------------------------------------------- #

def urn(cls: str, *parts: str) -> str:
    return "urn:inokron:" + cls + ":" + ":".join(str(p) for p in parts)


def _parcel_urn(barn_id: str) -> str:
    return f"urn:farmcalendar:FarmParcel:{barn_id}"


def _foi_parcel(barn_id: str) -> dict:
    return {"@id": _parcel_urn(barn_id), "@type": "Parcel"}


# --------------------------------------------------------------------------- #
#  SOSA observation builders                                                    #
# --------------------------------------------------------------------------- #

def _obs(obs_id: str, prop: Any, value: float | None, unit: str | None) -> dict:
    return {
        "@id": obs_id,
        "@type": "Observation",
        "observedProperty": prop,
        "hasResult": {"@type": "Result", "numericValue": value, "unit": unit},
    }


def _temp_obs(pid: str, v):   return _obs(f"{pid}:temp",    "cf:air_temperature",            v, "qudt:DEG_C")
def _hum_obs(pid: str, v):    return _obs(f"{pid}:hum",     "cf:relative_humidity",          v, "qudt:PERCENT")
def _thi_obs(pid: str, v):    return _obs(f"{pid}:thi",     "cf:temperature_humidity_index", v, None)
def _wind_obs(pid: str, v):   return _obs(f"{pid}:wind",    "cf:wind_speed",                 v, "qudt:M-PER-SEC")
def _windir_obs(pid: str, v): return _obs(f"{pid}:winddir", "cf:wind_from_direction",        v, "qudt:DEG")
def _precip_obs(pid: str, v): return _obs(f"{pid}:precip",  "cf:precipitation_amount",       v, "qudt:MilliM")
def _rain3h_obs(pid: str, v): return _obs(f"{pid}:rain3h",  "cf:precipitation_amount",       v, "qudt:MilliM")


def _iso(t) -> str:
    if isinstance(t, datetime):
        return t.isoformat()
    return str(t) if t is not None else ""


def _thm_members(pid: str, temperature, humidity, thi) -> list[dict]:
    members = []
    if temperature is not None:
        members.append(_temp_obs(pid, temperature))
    if humidity is not None:
        members.append(_hum_obs(pid, humidity))
    if thi is not None:
        members.append(_thi_obs(pid, thi))
    return members


# --------------------------------------------------------------------------- #
#  §2.1  Weather history row → WeatherObserved ObservationCollection           #
# --------------------------------------------------------------------------- #

def weather_history_row_to_ld(barn_id: str, row: dict) -> dict:
    ts = _iso(row.get("obs_time"))
    node_id = urn("WeatherObserved", barn_id, ts)
    return {
        "@id": node_id,
        "@type": ["ObservationCollection", "WeatherObserved"],
        "resultTime": ts,
        "phenomenonTime": ts,
        "hasFeatureOfInterest": _foi_parcel(barn_id),
        "hasMember": _thm_members(node_id, row.get("temperature"), row.get("humidity"), row.get("thi")),
    }


# --------------------------------------------------------------------------- #
#  §2.2  Current weather → WeatherObserved (FoI = Point)                       #
# --------------------------------------------------------------------------- #

def current_weather_to_ld(data: dict) -> dict:
    ts = _iso(data.get("obs_time"))
    node_id = urn("WeatherObserved", str(uuid.uuid4()))
    foi_id = urn("WeatherObserved", "foi", str(uuid.uuid4()))
    return {
        "@id": node_id,
        "@type": ["ObservationCollection", "WeatherObserved"],
        "resultTime": ts,
        "phenomenonTime": ts,
        "hasFeatureOfInterest": {
            "@id": foi_id,
            "@type": ["FeatureOfInterest", "Point"],
            "lat": data.get("lat"),
            "long": data.get("lon"),
        },
        "hasMember": _thm_members(node_id, data.get("temperature"), data.get("humidity"), data.get("thi")),
    }


# --------------------------------------------------------------------------- #
#  §2.3  Forecast point → WeatherForecast ObservationCollection                #
# --------------------------------------------------------------------------- #

def forecast_point_to_ld(barn_id: str, point: dict, source: str) -> dict:
    ts = _iso(point.get("forecast_for"))
    node_id = urn("WeatherForecast", barn_id, ts)
    members = _thm_members(node_id, point.get("temperature"), point.get("humidity"), point.get("thi"))
    if point.get("wind_speed") is not None:
        members.append(_wind_obs(node_id, point["wind_speed"]))
    if point.get("wind_direction") is not None:
        members.append(_windir_obs(node_id, point["wind_direction"]))
    if point.get("precipitation") is not None:
        members.append(_precip_obs(node_id, point["precipitation"]))
    if point.get("rainfall_3h") is not None:
        members.append(_rain3h_obs(node_id, point["rainfall_3h"]))
    return {
        "@id": node_id,
        "@type": ["ObservationCollection", "WeatherForecast"],
        "resultTime": ts,
        "phenomenonTime": ts,
        "hasFeatureOfInterest": _foi_parcel(barn_id),
        "hasMember": members,
        "source": source,
    }


# --------------------------------------------------------------------------- #
#  §2.4  Heat-stress status → WeatherObserved + optional WeatherAlert          #
# --------------------------------------------------------------------------- #

def heat_stress_status_to_ld(data: dict) -> list[dict]:
    barn_id = data.get("barn_id", "")
    ts = _iso(data.get("observation_time"))
    node_id = urn("WeatherObserved", barn_id, ts)

    members = _thm_members(node_id, data.get("temperature_c"), data.get("humidity_percent"), data.get("current_thi"))
    thi_node_id = f"{node_id}:thi" if data.get("current_thi") is not None else None

    collection = {
        "@id": node_id,
        "@type": ["ObservationCollection", "WeatherObserved"],
        "resultTime": ts,
        "phenomenonTime": ts,
        "hasFeatureOfInterest": _foi_parcel(barn_id),
        "hasMember": members,
    }
    graph = [collection]

    stress_level = data.get("stress_level") or {}
    severity = stress_level.get("severity", "normal")
    if severity and severity != "normal":
        desc = stress_level.get("description", "")
        rec = data.get("recommendation", "")
        if rec:
            desc = f"{desc} {rec}".strip()

        alert: dict = {
            "@id": urn("Alert", barn_id, "heatstress", ts),
            "@type": "WeatherAlert",
            "category": "heat stress",
            "subCategory": severity,
            "severity": severity,
            "description": desc,
            "dateIssued": ts,
            "hasFeatureOfInterest": _foi_parcel(barn_id),
        }
        if thi_node_id:
            alert["relatedObservation"] = {"@id": thi_node_id}
            alert["quantityValue"] = {"numericValue": data.get("current_thi"), "unit": "qudt:UNITLESS"}
        if data.get("edge_parameters"):
            alert["edge_parameters"] = data["edge_parameters"]
        graph.append(alert)

    return graph


# --------------------------------------------------------------------------- #
#  §2.5  Feeding-drop risk → WeatherAlert (predictive)                         #
# --------------------------------------------------------------------------- #

def feeding_drop_risk_to_ld(data: dict) -> list[dict]:
    barn_id = data.get("barn_id", "")
    issued = datetime.now(timezone.utc).isoformat()
    _severity_map = {"low": "info", "moderate": "medium", "severe": "high"}
    severity = _severity_map.get(data.get("risk_level", "low"), "info")
    desc = data.get("message", "")
    rec = data.get("recommendation", "")
    if rec:
        desc = f"{desc} {rec}".strip()

    return [{
        "@id": urn("Alert", barn_id, "feeddrop", issued),
        "@type": "WeatherAlert",
        "category": "heat stress",
        "subCategory": "feed intake reduction",
        "severity": severity,
        "description": desc,
        "dateIssued": issued,
        "validFrom": issued,
        "hasFeatureOfInterest": _foi_parcel(barn_id),
        "quantityValue": {
            "numericValue": data.get("expected_feed_drop_percent_min"),
            "unit": "qudt:PERCENT",
        },
        "feedDropPercentMax": data.get("expected_feed_drop_percent_max"),
        "consecutiveHoursAboveThreshold": {
            "above78": data.get("consecutive_hours_above_78"),
            "above84": data.get("consecutive_hours_above_84"),
        },
    }]


# --------------------------------------------------------------------------- #
#  §2.6  Severe heat-stress predictions → WeatherAlert per event               #
# --------------------------------------------------------------------------- #

def severe_heat_stress_to_ld(data: dict) -> list[dict]:
    barn_id = data.get("barn_id", "")
    rec = data.get("recommendation")
    graph = []
    for event in data.get("all_events", []):
        start = _iso(event.get("start_time"))
        end = _iso(event.get("end_time"))
        alert: dict = {
            "@id": urn("Alert", barn_id, "severeheat", start),
            "@type": "WeatherAlert",
            "category": "heat stress",
            "subCategory": "severe heat event",
            "severity": "high",
            "validFrom": start,
            "validTo": end,
            "hasFeatureOfInterest": _foi_parcel(barn_id),
            "quantityValue": {"numericValue": event.get("peak_thi"), "unit": "qudt:UNITLESS"},
            "avgThi": event.get("avg_thi"),
            "durationHours": event.get("duration_hours"),
        }
        if rec:
            alert["recommendation"] = rec
        graph.append(alert)
    return graph


# --------------------------------------------------------------------------- #
#  §2.7  Feed level row → SOSA Observation                                     #
# --------------------------------------------------------------------------- #

def feed_level_to_ld(row: dict) -> dict:
    fl_id = str(row.get("feeding_location_id", ""))
    ts = _iso(row.get("time"))
    node_id = urn("Observation", fl_id, "feedlevel", ts)
    barn_id = str(row.get("barn_id", ""))

    result: dict = {
        "@id": node_id,
        "@type": "Observation",
        "observedProperty": {
            "@type": ["ObservableProperty", "FeedLevel"],
            "description": "Feed level (percentage full)",
        },
        "resultTime": ts,
        "phenomenonTime": ts,
        "hasResult": {"@type": "Result", "numericValue": row.get("feed_level"), "unit": "qudt:PERCENT"},
        "hasFeatureOfInterest": {
            "@id": urn("FeedingLocation", fl_id),
            "@type": "FeatureOfInterest",
            "name": row.get("location_name"),
            "identifier": row.get("external_id"),
            "isLocatedIn": {"@id": _parcel_urn(barn_id)},
        },
    }
    if row.get("device_eui"):
        result["madeBySensor"] = {"@id": urn("Sensor", row["device_eui"]), "@type": "Sensor"}
    if barn_id:
        result["isObservedBySite"] = {"@id": _parcel_urn(barn_id)}
    return result


# --------------------------------------------------------------------------- #
#  §2.9  Feed alert row → Alert / WeatherAlert                                 #
# --------------------------------------------------------------------------- #

_HEAT_ALERT_TYPES = {"heat_stress", "heat_stress_alert"}


def feed_alert_to_ld(row: dict) -> dict:
    alert_id = str(row.get("alert_id", ""))
    barn_id = str(row.get("barn_id", ""))
    fl_id = row.get("feeding_location_id")
    alert_type = row.get("alert_type", "")
    created_at = _iso(row.get("created_at"))
    resolved_at = _iso(row.get("resolved_at")) if row.get("resolved_at") else None

    ld_type = "WeatherAlert" if alert_type in _HEAT_ALERT_TYPES else "Alert"
    alert_data = row.get("alert_data") or {}
    description = row.get("message") or alert_data.get("message", "")

    node: dict = {
        "@id": urn("Alert", alert_id),
        "@type": ld_type,
        "category": alert_type,
        "subCategory": alert_type,
        "severity": row.get("severity"),
        "description": description,
        "dateIssued": created_at,
        "status": row.get("status"),
        "origin": row.get("origin"),
        "hasFeatureOfInterest": _foi_parcel(barn_id) if barn_id else None,
    }
    if resolved_at:
        node["validTo"] = resolved_at
    # Predicted alerts carry the forecast time the condition is expected.
    predicted_for = _iso(row.get("predicted_for")) if row.get("predicted_for") else None
    if predicted_for:
        node["predictedFor"] = predicted_for
    if fl_id:
        node["secondaryFeatureOfInterest"] = {
            "@id": urn("FeedingLocation", str(fl_id)),
            "@type": "FeatureOfInterest",
            "name": row.get("location_name"),
        }
    numerics = {k: v for k, v in alert_data.items() if isinstance(v, (int, float))}
    if numerics:
        first_val = next(iter(numerics.values()))
        node["quantityValue"] = {"numericValue": first_val, "unit": "qudt:UNITLESS"}

    return {k: v for k, v in node.items() if v is not None}
