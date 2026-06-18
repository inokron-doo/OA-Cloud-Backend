from datetime import timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

FARM_TIMEZONE = ZoneInfo("Europe/Ljubljana")


def get_timezone(settings: dict) -> ZoneInfo:
    return ZoneInfo(settings.get("prediction_timezone", "Europe/Ljubljana"))


def iso_utc(value) -> str | None:
    if value is None:
        return None
    ts = pd.to_datetime(value, utc=True)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    return ts.tz_convert("UTC").isoformat()


def iso_local(value, tz: ZoneInfo) -> str | None:
    if value is None:
        return None
    ts = pd.to_datetime(value, utc=True)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    return ts.tz_convert(tz).isoformat()


def clean_history(history: list, settings: dict) -> pd.DataFrame:
    df = pd.DataFrame(history)
    if df.empty:
        return df

    tz = get_timezone(settings)
    df = df.copy()
    df = df.rename(columns={"numeric_value": "feed_level_pct"})
    df["time"] = pd.to_datetime(df["time"], utc=True, errors="coerce")
    df["local_time"] = df["time"].dt.tz_convert(tz)
    df["feed_level_pct"] = pd.to_numeric(df["feed_level_pct"], errors="coerce")

    min_percent = float(settings.get("prediction_outlier_min_percent", 0))
    max_percent = float(settings.get("prediction_outlier_max_percent", 100))
    df = df[
        (df["feed_level_pct"] >= min_percent)
        & (df["feed_level_pct"] <= max_percent)
    ]

    df = df.dropna(subset=["time", "feed_level_pct"])
    df = df.sort_values("time")
    df = df.drop_duplicates(subset=["time"], keep="last")
    return df


def add_rate_features(df: pd.DataFrame, settings: dict) -> pd.DataFrame:
    if df.empty:
        return df

    df = df.copy()
    df["previous_level"] = df["feed_level_pct"].shift(1)
    df["previous_time"] = df["time"].shift(1)
    df["level_diff"] = df["feed_level_pct"] - df["previous_level"]
    df["time_diff_h"] = (
        df["time"] - df["previous_time"]
    ).dt.total_seconds() / 3600.0
    df["hour"] = df["local_time"].dt.hour

    day_start = int(settings.get("prediction_day_start_hour", 6))
    night_start = int(settings.get("prediction_night_start_hour", 18))
    df["period"] = np.where(
        (df["hour"] >= day_start) & (df["hour"] < night_start),
        "day",
        "night",
    )

    drop_threshold = float(settings.get("prediction_sudden_drop_percent", 15))
    rise_threshold = float(settings.get("prediction_sudden_rise_percent", 15))
    df["sudden_drop"] = df["level_diff"] < -drop_threshold
    df["sudden_rise"] = df["level_diff"] > rise_threshold

    max_gap = float(settings.get("prediction_max_time_gap_hours", 2))
    valid = (
        (df["time_diff_h"] > 0)
        & (df["time_diff_h"] <= max_gap)
        & (df["level_diff"] < 0)
        & (~df["sudden_drop"])
        & (~df["sudden_rise"])
    )

    df["consumption_rate_percent_per_hour"] = np.where(
        valid,
        -df["level_diff"] / df["time_diff_h"],
        np.nan,
    )

    min_rate = float(settings.get("prediction_min_rate_percent_per_hour", 0.05))
    max_rate = float(settings.get("prediction_max_rate_percent_per_hour", 8.0))
    in_range = (
        (df["consumption_rate_percent_per_hour"] >= min_rate)
        & (df["consumption_rate_percent_per_hour"] <= max_rate)
    )

    df["valid_rate_row"] = valid & in_range
    df.loc[~df["valid_rate_row"], "consumption_rate_percent_per_hour"] = np.nan
    return df


def compute_window_rate(
    df: pd.DataFrame,
    period: str,
    hours: int | None = None,
    days: int | None = None,
    settings: dict | None = None,
) -> dict:
    if df.empty:
        return {"rate": None, "samples": 0}

    latest_time = df["time"].max()
    start_time = None
    if hours is not None:
        start_time = latest_time - pd.Timedelta(hours=hours)
    if days is not None:
        start_time = latest_time - pd.Timedelta(days=days)

    filtered = df
    if start_time is not None:
        filtered = filtered[filtered["time"] >= start_time]

    filtered = filtered[
        (filtered["valid_rate_row"]) & (filtered["period"] == period)
    ]

    if filtered.empty:
        return {"rate": None, "samples": 0}

    rate = float(filtered["consumption_rate_percent_per_hour"].median())
    return {"rate": rate, "samples": int(len(filtered))}


def blend_rates(short: dict, medium: dict, long: dict, settings: dict) -> float | None:
    weights = {
        "short": float(settings.get("prediction_rate_blend_short_weight", 0.5)),
        "medium": float(settings.get("prediction_rate_blend_medium_weight", 0.3)),
        "long": float(settings.get("prediction_rate_blend_long_weight", 0.2)),
    }

    entries = []
    if short.get("rate") is not None:
        entries.append((short["rate"], weights["short"]))
    if medium.get("rate") is not None:
        entries.append((medium["rate"], weights["medium"]))
    if long.get("rate") is not None:
        entries.append((long["rate"], weights["long"]))

    if not entries:
        return None

    weight_total = sum(weight for _, weight in entries)
    if weight_total <= 0:
        return None

    return sum(rate * weight for rate, weight in entries) / weight_total


def compute_day_night_rates(df: pd.DataFrame, settings: dict) -> dict:
    short_hours = int(settings.get("prediction_short_window_hours", 24))
    medium_days = int(settings.get("prediction_medium_window_days", 7))
    long_days = int(settings.get("prediction_long_window_days", 30))

    day_short = compute_window_rate(df, "day", hours=short_hours, settings=settings)
    day_medium = compute_window_rate(df, "day", days=medium_days, settings=settings)
    day_long = compute_window_rate(df, "day", days=long_days, settings=settings)

    night_short = compute_window_rate(
        df, "night", hours=short_hours, settings=settings
    )
    night_medium = compute_window_rate(
        df, "night", days=medium_days, settings=settings
    )
    night_long = compute_window_rate(df, "night", days=long_days, settings=settings)

    day_final = blend_rates(day_short, day_medium, day_long, settings)
    night_final = blend_rates(night_short, night_medium, night_long, settings)

    if day_final is None and night_final is not None:
        day_final = night_final
    if night_final is None and day_final is not None:
        night_final = day_final
    if day_final is None and night_final is None:
        day_final = 1.0
        night_final = 1.0

    min_rate = float(settings.get("prediction_min_rate_percent_per_hour", 0.05))
    max_rate = float(settings.get("prediction_max_rate_percent_per_hour", 8.0))

    day_final = float(min(max(day_final, min_rate), max_rate))
    night_final = float(min(max(night_final, min_rate), max_rate))

    return {
        "day": {
            "short_rate": day_short["rate"],
            "medium_rate": day_medium["rate"],
            "long_rate": day_long["rate"],
            "final_rate": day_final,
            "samples": {
                "short": day_short["samples"],
                "medium": day_medium["samples"],
                "long": day_long["samples"],
            },
        },
        "night": {
            "short_rate": night_short["rate"],
            "medium_rate": night_medium["rate"],
            "long_rate": night_long["rate"],
            "final_rate": night_final,
            "samples": {
                "short": night_short["samples"],
                "medium": night_medium["samples"],
                "long": night_long["samples"],
            },
        },
    }


def get_thi_multiplier(thi: float | None, settings: dict) -> float:
    if not settings.get("prediction_thi_enabled", True):
        return 1.0
    if thi is None or pd.isna(thi):
        return 1.0

    mild = float(settings.get("prediction_thi_mild_threshold", 68))
    high = float(settings.get("prediction_thi_high_threshold", 72))
    severe = float(settings.get("prediction_thi_severe_threshold", 80))

    mild_mult = float(settings.get("prediction_thi_mild_rate_multiplier", 1.05))
    high_mult = float(settings.get("prediction_thi_high_rate_multiplier", 1.15))
    severe_mult = float(settings.get("prediction_thi_severe_rate_multiplier", 1.3))

    if thi >= severe:
        return severe_mult
    if thi >= high:
        return high_mult
    if thi >= mild:
        return mild_mult
    return 1.0


def normalize_feeding_events(feeding_events: list, settings: dict) -> list:
    import re

    tz = get_timezone(settings)
    normalized = []
    pattern = re.compile(r"\((?P<qty>[\d.]+)\s*kg\)", re.IGNORECASE)

    for event in feeding_events:
        source = event.get("activity", event)
        parsed = event.get("parsed", {})

        scheduled_time = (
            source.get("start_datetime")
            or source.get("scheduled_time")
            or source.get("time")
        )
        if not scheduled_time:
            continue

        scheduled_time = pd.to_datetime(scheduled_time, utc=True, errors="coerce")
        if pd.isna(scheduled_time):
            continue

        title = source.get("title") or event.get("title")
        quantity_kg = parsed.get("quantity_kg")
        if quantity_kg is None:
            quantity_kg = source.get("quantity_kg")
        if quantity_kg is None and title:
            match = pattern.search(title)
            if match:
                quantity_kg = float(match.group("qty"))

        normalized.append(
            {
                "scheduled_time": scheduled_time,
                "scheduled_local_time": scheduled_time.tz_convert(tz),
                "quantity_kg": quantity_kg,
                "title": title,
                "source_location_key": parsed.get("source_location_key")
                or source.get("source_location_key"),
            }
        )

    normalized.sort(key=lambda row: row["scheduled_time"])
    return normalized


def estimate_trough_capacity_kg(
    df: pd.DataFrame, feeding_events: list, settings: dict
) -> dict:
    default_capacity = float(settings.get("prediction_capacity_default_kg", 3000))
    if not settings.get("prediction_capacity_estimation_enabled", True):
        return {
            "capacity_kg": default_capacity,
            "method": "default",
            "samples": 0,
            "sample_estimates": [],
        }

    min_capacity = float(settings.get("prediction_capacity_min_kg", 500))
    max_capacity = float(settings.get("prediction_capacity_max_kg", 15000))
    min_jump = float(settings.get("prediction_capacity_min_jump_percent", 5))
    match_window = pd.Timedelta(minutes=30)
    rise_window = pd.Timedelta(hours=2)

    estimates = []
    for event in feeding_events:
        quantity_kg = event.get("quantity_kg")
        if quantity_kg is None or float(quantity_kg) <= 0:
            continue

        event_time = event.get("scheduled_time")
        if event_time is None:
            continue

        before = df[
            (df["time"] >= event_time - match_window)
            & (df["time"] <= event_time + match_window)
        ]
        if before.empty:
            continue

        before_level = float(
            before.loc[before["time"].sub(event_time).abs().idxmin()]["feed_level_pct"]
        )

        after = df[
            (df["time"] > event_time)
            & (df["time"] <= event_time + rise_window)
        ].sort_values("time")
        if after.empty:
            continue

        peak_level = before_level
        for _, row in after.iterrows():
            val = float(row["feed_level_pct"])
            if val > peak_level:
                peak_level = val
            else:
                break

        jump_percent = peak_level - before_level
        if jump_percent < min_jump:
            continue

        estimated_capacity = float(quantity_kg) / (jump_percent / 100.0)
        if min_capacity <= estimated_capacity <= max_capacity:
            estimates.append(estimated_capacity)

    if estimates:
        return {
            "capacity_kg": float(np.median(estimates)),
            "method": "historical_jump",
            "samples": len(estimates),
            "sample_estimates": estimates,
        }

    return {
        "capacity_kg": default_capacity,
        "method": "default",
        "samples": 0,
        "sample_estimates": [],
    }


def apply_due_refills(
    current_time: pd.Timestamp,
    level: float,
    pending_events: list,
    capacity_kg: float,
    tz: ZoneInfo,
) -> tuple[float, list, list]:
    applied = []
    remaining = []

    for event in pending_events:
        event_time = event.get("scheduled_time")
        if event_time is None or event_time > current_time:
            remaining.append(event)
            continue

        quantity_kg = event.get("quantity_kg")
        if quantity_kg is None:
            remaining.append(event)
            continue

        jump_percent = (float(quantity_kg) / capacity_kg) * 100.0
        level_before = level
        level_after = min(100.0, level + jump_percent)
        level = level_after

        applied.append(
            {
                "time": iso_utc(event_time),
                "local_time": iso_local(event_time, tz),
                "quantity_kg": quantity_kg,
                "jump_percent": round(jump_percent, 2),
                "level_before": round(level_before, 2),
                "level_after": round(level_after, 2),
                "title": event.get("title"),
            }
        )

    return level, applied, remaining


def simulate_forecast(
    df: pd.DataFrame,
    feeding_events: list,
    rates: dict,
    capacity_info: dict,
    settings: dict,
) -> tuple[list, list]:
    tz = get_timezone(settings)
    step_minutes = int(settings.get("prediction_resample_minutes", 15))
    forecast_hours = int(settings.get("prediction_forecast_hours", 24))
    output_step_minutes = 60

    start_time = df["time"].max()
    current_level = float(df.iloc[-1]["feed_level_pct"])
    end_time = start_time + pd.Timedelta(hours=forecast_hours)
    step = pd.Timedelta(minutes=step_minutes)
    output_step = pd.Timedelta(minutes=output_step_minutes)

    latest_thi = None
    if "thi" in df.columns:
        thi_series = df["thi"].dropna()
        if not thi_series.empty:
            latest_thi = float(thi_series.iloc[-1])

    pending_events = [
        e for e in feeding_events if e.get("scheduled_time") is not None
        and e["scheduled_time"] > start_time
    ]
    applied_refills = []
    forecast = []
    next_output_time = start_time

    current_time = start_time
    while current_time <= end_time:
        local_time = current_time.tz_convert(tz)
        hour = local_time.hour
        day_start = int(settings.get("prediction_day_start_hour", 6))
        night_start = int(settings.get("prediction_night_start_hour", 18))
        period = "night" if hour < day_start or hour >= night_start else "day"

        base_rate = float(rates[period]["final_rate"])
        thi_multiplier = get_thi_multiplier(latest_thi, settings)
        adjusted_rate = base_rate * thi_multiplier

        current_level, applied, pending_events = apply_due_refills(
            current_time,
            current_level,
            pending_events,
            float(capacity_info["capacity_kg"]),
            tz,
        )
        applied_refills.extend(applied)

        step_hours = step_minutes / 60.0
        current_level = max(0.0, current_level - (adjusted_rate * step_hours))

        emit = current_time >= next_output_time or bool(applied)
        if emit:
            forecast.append({
                "time": iso_utc(current_time),
                "level_percent": round(current_level, 2),
            })
            if current_time >= next_output_time:
                next_output_time = current_time + output_step

        current_time += step

    return forecast, applied_refills


def estimate_empty_at(forecast: list) -> str | None:
    for point in forecast:
        if point.get("level_percent") is not None and point["level_percent"] <= 0:
            return point.get("time")
    return None


def generate_feed_forecast(history: list, feeding_events: list, settings: dict) -> dict:
    df = clean_history(history, settings)
    tz = get_timezone(settings)

    if df.empty:
        return {
            "status": "no_data",
            "timezone": tz.key,
            "history_points": 0,
            "rate_points_used": 0,
            "feeding_events_count": len(feeding_events),
            "forecast": [],
            "alerts": [],
        }

    min_points = int(settings.get("prediction_min_points", 30))
    if len(df) < min_points:
        return {
            "status": "insufficient_data",
            "timezone": tz.key,
            "history_points": len(df),
            "rate_points_used": 0,
            "feeding_events_count": len(feeding_events),
            "forecast": [],
            "alerts": [],
        }

    df = add_rate_features(df, settings)
    normalized_events = normalize_feeding_events(feeding_events, settings)
    rates = compute_day_night_rates(df, settings)
    capacity_info = estimate_trough_capacity_kg(df, normalized_events, settings)

    forecast, applied_refills = simulate_forecast(
        df, normalized_events, rates, capacity_info, settings
    )

    latest_thi = None
    if "thi" in df.columns:
        thi_series = df["thi"].dropna()
        if not thi_series.empty:
            latest_thi = float(thi_series.iloc[-1])

    current_time = df["time"].iloc[-1]
    current_local_time = df["local_time"].iloc[-1]
    current_level = float(df.iloc[-1]["feed_level_pct"])

    ignored_points = {
        "sudden_drops": int(df["sudden_drop"].sum()),
        "sudden_rises": int(df["sudden_rise"].sum()),
        "invalid_rate_rows": int(((df["time_diff_h"] > 0) & (~df["valid_rate_row"])).sum()),
    }

    # Pure forecaster: alerting moved to the main backend's unified rule engine,
    # which runs the same thresholds over this forecast timeline. The service no
    # longer computes its own (duplicate-threshold) alerts.
    alerts = []

    return {
        "status": "success",
        "timezone": tz.key,
        "history_points": int(len(df)),
        "rate_points_used": int(df["valid_rate_row"].sum()),
        "feeding_events_count": len(normalized_events),
        "current_level_percent": round(current_level, 2),
        "current_time": iso_utc(current_time),
        "current_local_time": iso_local(current_local_time, tz),
        "current_thi": latest_thi,
        "day_consumption_rate_percent_per_hour": rates["day"]["final_rate"],
        "night_consumption_rate_percent_per_hour": rates["night"]["final_rate"],
        "rate_breakdown": rates,
        "capacity_kg": capacity_info["capacity_kg"],
        "capacity_estimation": capacity_info,
        "estimated_empty_at": estimate_empty_at(forecast),
        "forecast_hours": int(settings.get("prediction_forecast_hours", 24)),
        "step_minutes": int(settings.get("prediction_resample_minutes", 15)),
        "ignored_points": ignored_points,
        "applied_refills": applied_refills,
        "forecast": forecast,
        "alerts": alerts,
    }


def baseline_forecast(feeding_location_id: str, days: int) -> float:
    if days <= 0:
        return 0.0
    return 0.0
