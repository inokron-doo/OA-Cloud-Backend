"""Unified alert engine (observed pass).

One orchestrator that builds observed state, runs every rule family, and routes
ALL alerts through a single save + notify pipeline (`_emit`). This replaces the
two divergent save paths in the old AlertMonitor (heat via create_alert, feed via
_save_alert) so every alert is stored with consistent fields and notified the same
way.

Phase 1 scope: observed alerts only. Heat keeps its existing forecast-sustained
detection (now emitted through the unified path so it carries barn_name); feed-level
keeps low_feed / low_feed_recurring / stale-spoilage; MooHero is replaced by the
single rate-based health_spike. Predicted evaluation (continuous.evaluate over
forecast timelines), critical tiers, and severity->action routing arrive in
Phases 2-3.
"""

from __future__ import annotations

import logging
import os
import traceback
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from src.utils.db import PGDB
from src.utils.mail_utils import EmailService
from src.services.rules import continuous, event_rules, forecast, meta_rules, notify
from src.services.rules.continuous import (
    heat_stress_rule,
    low_feed_rule,
    spoilage_rule,
)

logger = logging.getLogger(__name__)

HEAT_STRESS_THI_THRESHOLD = float(os.getenv("HEAT_STRESS_THI_THRESHOLD", "72"))
SEVERE_HEAT_THI_THRESHOLD = float(os.getenv("SEVERE_HEAT_THI_THRESHOLD", "80"))
ALERT_COOLDOWN_HOURS = int(os.getenv("ALERT_COOLDOWN_HOURS", "6"))
ALERT_TIMEZONE = os.getenv("ALERT_TIMEZONE", "UTC")
ALERT_ADMIN_EMAIL = os.getenv("ALERT_ADMIN_EMAIL") or os.getenv("ADMIN_EMAIL") or ""
ALERT_EXPIRY_HOURS = int(os.getenv("ALERT_EXPIRY_HOURS", "48"))

# Which rules may email their PREDICTED alerts by default (severity still gates the
# action; this is the per-rule on/off the farmer can override via rule_config).
# Default: heat predictions notify; feed-level predictions are display-only.
_PREDICT_NOTIFY_DEFAULT = {
    "heat_stress": True,
    "low_feed": False,
    "spoilage_risk": False,
    "cancel_feeding_suggestion": False,
}


class AlertEngine:
    def __init__(self, db=None, email_service=None):
        self.db = db or PGDB()
        self.email_service = email_service or EmailService()

    # --- coercion / time helpers ---
    @staticmethod
    def _as_float(value, default):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _as_int(value, default):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.now(ZoneInfo("UTC"))

    def _local_tz(self):
        try:
            return ZoneInfo(ALERT_TIMEZONE)
        except Exception:
            return ZoneInfo("UTC")

    def _get_admin_emails(self):
        return [e.strip() for e in ALERT_ADMIN_EMAIL.split(",") if e.strip()]

    # --- unified save + notify pipeline ---
    async def _emit(self, alert_data: dict):
        """Persist one observed alert and route its notification.

        Severity -> action map decides display-only vs email (same map used for
        predicted alerts). Observed alerts email immediately when the action wants
        email; info-level alerts are display-only.
        """
        alert_data.setdefault("origin", "observed")
        result = self.db.save_alert(alert_data)
        created_at = result.get("created_at") if result else self._utc_now()
        if notify.email_for_severity(alert_data.get("severity"), self._routing()):
            await self.send_alert_email(
                alert_data.get("barn_id"),
                {
                    "alert_type": alert_data.get("alert_type"),
                    "severity": alert_data.get("severity"),
                    "message": alert_data.get("message"),
                    "location_name": alert_data.get("location_name"),
                    "created_at": created_at,
                },
            )

    async def send_alert_email(self, barn_id: str, alert: dict) -> bool:
        """Email the alert to admins. Returns True only if at least one email was
        actually sent — predicted alerts use this to stamp email_sent_at only on a
        real send, so a missing SMTP/admin config doesn't burn the at-most-once
        budget (it can email once configured)."""
        try:
            admin_emails = self._get_admin_emails()
            if not admin_emails:
                logger.warning(
                    "No admin alert email configured. Set ALERT_ADMIN_EMAIL or ADMIN_EMAIL"
                )
                return False

            barn = self.db.get_barn_by_id(barn_id) if barn_id else None
            barn_name = (
                barn.get("barn_name") or barn.get("name") or "Unknown Barn"
            ) if barn else "Unknown Barn"

            payload = {
                "alert_type": (alert.get("alert_type") or "alert").replace("_", " ").title(),
                "severity": alert.get("severity"),
                "barn_name": barn_name,
                "message": alert.get("message"),
                "timestamp": alert.get("created_at"),
            }

            any_sent = False
            for email in admin_emails:
                try:
                    sent = await self.email_service.send_alert_email_async(email, payload)
                    if sent:
                        any_sent = True
                        logger.info(f"Alert email sent to admin {email} for barn {barn_name}")
                    else:
                        logger.error(
                            f"Alert email failed for {email} for barn {barn_name}. "
                            f"SMTP accepted configuration but send returned False"
                        )
                except Exception as e:
                    logger.error(f"Failed to send alert email to {email}: {e}")
            return any_sent
        except Exception as e:
            logger.error(f"Error sending alert email: {e}")
            traceback.print_exc()
            return False

    def _rule_config(self, rule_type: str, feeding_location_id: str = None) -> dict:
        """Per-rule config JSON (enabled, severity, prediction_enabled,
        prediction_horizon_hours, notify_on_predict) from alert_thresholds,
        location override winning."""
        cfg = self.db.get_threshold_value(
            f"rule_config:{rule_type}", feeding_location_id=feeding_location_id, default=None
        )
        return cfg if isinstance(cfg, dict) else {}

    def _routing(self):
        r = self.db.get_threshold_value("notification_routing", default=None)
        return r if isinstance(r, dict) else None

    def _debounce_cycles(self) -> int:
        return self._as_int(self.db.get_threshold_value("alert_debounce_cycles", default=3), 3)

    def _notify_on_predict(self, rule_type: str) -> bool:
        """Whether a rule's PREDICTED alerts may email (severity still gates the
        action). Default: heat predictions notify; feed-level predictions are
        display-only, per the agreed default. Overridable via rule_config."""
        cfg = self._rule_config(rule_type)
        return bool(cfg.get("notify_on_predict", _PREDICT_NOTIFY_DEFAULT.get(rule_type, False)))

    async def _emit_predicted(self, alert_data: dict, dedupe_key: str):
        """Persist/refresh a predicted alert (self-dedupes via dedupe_key), then
        route + debounce its email.

        Email fires only when: the severity routes to email/both, the rule allows
        predicted notifications, the crossing has persisted >= debounce cycles, and
        it has not already emailed (at-most-once via email_sent_at)."""
        alert_data["origin"] = "predicted"
        result = self.db.upsert_predicted_alert(alert_data, dedupe_key)
        if not result:
            return

        if not notify.email_for_severity(alert_data.get("severity"), self._routing()):
            return
        if not self._notify_on_predict(alert_data.get("alert_type")):
            return
        if notify.predicted_email_due(
            self._as_int(result.get("cycles_seen"), 1),
            self._debounce_cycles(),
            already_emailed=result.get("email_sent_at") is not None,
        ):
            sent = await self.send_alert_email(
                alert_data.get("barn_id"),
                {
                    "alert_type": alert_data.get("alert_type"),
                    "severity": alert_data.get("severity"),
                    "message": alert_data.get("message"),
                    "location_name": alert_data.get("location_name"),
                    "created_at": result.get("created_at") or self._utc_now(),
                },
            )
            if sent:
                self.db.mark_alert_emailed(result.get("alert_id"))

    # --- heat stress (observed; sustained THI over the recent observed window) ---
    async def check_heat_stress(self):
        try:
            for barn in self.db.get_all_barns():
                barn_id = barn.get("id") or barn.get("barn_id")
                if not barn_id:
                    continue

                cfg = self._rule_config("heat_stress")
                if not cfg.get("enabled", True):
                    continue

                thi_warn = self._as_float(
                    self.db.get_threshold_value(
                        "heat_stress_thi_threshold", barn_id=barn_id, default=HEAT_STRESS_THI_THRESHOLD
                    ),
                    HEAT_STRESS_THI_THRESHOLD,
                )
                thi_crit = self._as_float(
                    self.db.get_threshold_value(
                        "severe_heat_thi_threshold", barn_id=barn_id, default=SEVERE_HEAT_THI_THRESHOLD
                    ),
                    SEVERE_HEAT_THI_THRESHOLD,
                )
                warn_min = self._as_int(
                    self.db.get_threshold_value(
                        "heat_stress_duration_minutes", barn_id=barn_id, default=240
                    ),
                    240,
                )
                crit_min = self._as_int(
                    self.db.get_threshold_value(
                        "severe_heat_duration_minutes", barn_id=barn_id, default=360
                    ),
                    360,
                )
                cooldown_hours = self._as_int(
                    self.db.get_threshold_value(
                        "alert_cooldown_hours", barn_id=barn_id, default=ALERT_COOLDOWN_HOURS
                    ),
                    ALERT_COOLDOWN_HOURS,
                )

                lookback_hours = int(max(warn_min, crit_min) / 60) + 2
                rows = self.db.get_weather_history(barn_id, hours=lookback_hours)
                samples = forecast.thi_timeline(rows, "obs_time")
                if not samples:
                    continue

                rule = heat_stress_rule(thi_warn, thi_crit, warn_min, crit_min)
                result = continuous.evaluate(rule, samples)  # observed: full window, no horizon
                if not result.crossed:
                    continue
                if self.db.get_recent_alerts(barn_id, "heat_stress", cooldown_hours):
                    logger.info(f"Heat stress alert for barn {barn_id} already sent recently, skipping")
                    continue

                thi_val = result.sample.values.get("thi") if result.sample else None
                label = "Severe heat stress" if result.severity == "critical" else "Heat stress"
                message = (
                    f"{label} detected (observed): THI {thi_val:.1f}."
                    if thi_val is not None
                    else f"{label} detected (observed)."
                )
                await self._emit(
                    {
                        "alert_type": "heat_stress",
                        "severity": result.severity,
                        "barn_id": barn_id,
                        "barn_name": barn.get("name"),
                        "feeding_location_id": None,
                        "location_name": None,
                        "message": message,
                        "thi": round(thi_val, 1) if thi_val is not None else None,
                    }
                )
                logger.info(f"Heat stress alert created for barn {barn_id}: {message}")
        except Exception as e:
            logger.error(f"Error checking heat stress: {e}")
            traceback.print_exc()

    # --- feed level (observed; low_feed + recurrence + stale-spoilage + events) ---
    async def check_feed_level(self):
        try:
            local_tz = self._local_tz()
            now_utc = self._utc_now()

            for barn in self.db.get_all_barns():
                barn_id = barn.get("id") or barn.get("barn_id")
                if not barn_id:
                    continue

                cooldown_hours = self._as_int(
                    self.db.get_threshold_value(
                        "alert_cooldown_hours", barn_id=barn_id, default=ALERT_COOLDOWN_HOURS
                    ),
                    ALERT_COOLDOWN_HOURS,
                )
                locations = self.db.get_feeding_locations_by_barn(barn_id)
                schedules = self.db.get_feeding_schedules(barn_id=barn_id, is_active=True)

                for location in locations:
                    feeding_location_id = location.get("feeding_location_id")
                    if not feeding_location_id:
                        continue
                    location_name = location.get("name")

                    def thr(key, default):
                        return self.db.get_threshold_value(
                            key, barn_id=barn_id, feeding_location_id=feeding_location_id, default=default
                        )

                    stale_minutes = self._as_int(thr("feed_stale_minutes", 60), 60)
                    stale_change_percent = self._as_float(thr("feed_stale_change_percent", 1), 1)
                    low_feed_percent = self._as_float(thr("low_feed_percent", 20), 20)
                    low_feed_critical_percent = self._as_float(thr("low_feed_critical_percent", 10), 10)
                    spoilage_feed_percent = self._as_float(thr("spoilage_feed_percent", 70), 70)
                    spoilage_stale_hours = self._as_int(thr("spoilage_stale_hours", 8), 8)
                    spoilage_temp_c = self._as_float(thr("spoilage_temp_c", 25), 25)
                    feed_rise_percent = self._as_float(thr("feed_rise_percent", 5), 5)
                    feed_rise_lookback_minutes = self._as_int(thr("feed_rise_lookback_minutes", 60), 60)
                    unexpected_cooldown_minutes = self._as_int(thr("unexpected_feed_cooldown_minutes", 120), 120)
                    recurrence_count = self._as_int(thr("low_feed_recurrence_count", 3), 3)
                    recurrence_days = self._as_int(thr("low_feed_recurrence_days", 7), 7)
                    suggested_kg = self._as_float(thr("feeding_suggestion_min_kg", 10), 10)

                    history = self.db.get_feed_level_history_for_location(feeding_location_id, stale_minutes)
                    values = [h["numeric_value"] for h in history if h.get("numeric_value") is not None]
                    if not values:
                        continue
                    delta = max(values) - min(values)
                    current_level = values[-1]
                    stale = delta <= stale_change_percent
                    latest_temp = history[-1].get("temperature") if history else None

                    # low_feed (+ recurring) — observed stale-gate preserved; severity
                    # (warning/critical) via the same rule used for the predicted path.
                    if stale and current_level <= low_feed_percent:
                        low_result = continuous.evaluate(
                            low_feed_rule(low_feed_percent, low_feed_critical_percent),
                            [continuous.Sample(now_utc, {"feed_level_pct": current_level})],
                        )
                        low_severity = low_result.severity or "warning"
                        if not self.db.get_recent_alert_for_location(
                            barn_id, "low_feed", feeding_location_id, cooldown_hours
                        ):
                            await self._emit(
                                {
                                    "alert_type": "low_feed",
                                    "severity": low_severity,
                                    "barn_id": barn_id,
                                    "barn_name": barn.get("name"),
                                    "feeding_location_id": feeding_location_id,
                                    "location_name": location_name,
                                    "message": (
                                        f"Low feed level detected at {location_name} "
                                        f"({current_level:.1f}%)."
                                    ),
                                    "suggested_kg": suggested_kg,
                                    "current_level": round(current_level, 1),
                                    "threshold": low_feed_percent,
                                }
                            )

                        count = self.db.get_alert_count_for_location(
                            "low_feed", feeding_location_id, recurrence_days
                        )
                        if count >= recurrence_count and not self.db.get_recent_alert_for_location(
                            barn_id, "low_feed_recurring", feeding_location_id, cooldown_hours
                        ):
                            await self._emit(
                                {
                                    "alert_type": "low_feed_recurring",
                                    "severity": "warning",
                                    "barn_id": barn_id,
                                    "barn_name": barn.get("name"),
                                    "feeding_location_id": feeding_location_id,
                                    "location_name": location_name,
                                    "message": (
                                        f"Low feed has recurred {count} times in the last "
                                        f"{recurrence_days} days at {location_name}."
                                    ),
                                }
                            )

                    # spoilage_risk — stale-high-warm only (refill-pattern variant removed by design)
                    spoilage_minutes = max(spoilage_stale_hours * 60, stale_minutes)
                    spoilage_history = self.db.get_feed_level_history_for_location(
                        feeding_location_id, spoilage_minutes
                    )
                    spoilage_values = [
                        h["numeric_value"] for h in spoilage_history if h.get("numeric_value") is not None
                    ]
                    spoilage_stale = False
                    if len(spoilage_values) >= 2:
                        spoilage_delta = max(spoilage_values) - min(spoilage_values)
                        first_time = spoilage_history[0].get("time")
                        last_time = spoilage_history[-1].get("time")
                        covered_minutes = 0
                        if first_time and last_time:
                            covered_minutes = (last_time - first_time).total_seconds() / 60
                        spoilage_stale = (
                            covered_minutes >= (spoilage_minutes * 0.8)
                            and spoilage_delta <= stale_change_percent
                        )

                    if spoilage_stale and current_level >= spoilage_feed_percent:
                        temp_ok = latest_temp is None or latest_temp >= spoilage_temp_c
                        if temp_ok and not self.db.get_recent_alert_for_location(
                            barn_id, "spoilage_risk", feeding_location_id, cooldown_hours
                        ):
                            await self._emit(
                                {
                                    "alert_type": "spoilage_risk",
                                    "severity": "warning",
                                    "barn_id": barn_id,
                                    "barn_name": barn.get("name"),
                                    "feeding_location_id": feeding_location_id,
                                    "location_name": location_name,
                                    "message": (
                                        f"Spoilage risk at {location_name}. "
                                        f"Feed level is {current_level:.1f}% and unchanged for "
                                        f"about {spoilage_stale_hours} hours."
                                    ),
                                    "current_level": round(current_level, 1),
                                }
                            )

                    await event_rules.check_missed_feeding(
                        self.db, self._emit, barn, location, schedules,
                        feed_rise_percent, cooldown_hours, now_utc, local_tz,
                    )
                    await event_rules.check_unexpected_feeding(
                        self.db, self._emit, barn, location, schedules,
                        feed_rise_percent, feed_rise_lookback_minutes,
                        unexpected_cooldown_minutes, now_utc, local_tz,
                    )
        except Exception as e:
            logger.error(f"Error checking feed level alerts: {e}")
            traceback.print_exc()

    # --- health spike (observed; MooHero rate rule with cause attribution) ---
    async def check_health(self):
        try:
            now_utc = self._utc_now()
            for barn in self.db.get_all_barns():
                barn_id = barn.get("id") or barn.get("barn_id")
                if not barn_id:
                    continue
                locations = self.db.get_feeding_locations_by_barn(barn_id)
                await meta_rules.check_health_spike(self.db, self._emit, barn, locations, now_utc)
        except Exception as e:
            logger.error(f"Error checking health spikes: {e}")
            traceback.print_exc()

    # --- predicted alerts (forecast window; same rules over forecast timelines) ---
    async def check_predicted(self):
        """Run the continuous rules over forecast timelines (weather + feed) and
        upsert predicted alerts. Display-only in Phase 2. Tracks which (rule, scope)
        had data so reaping only clears predictions whose source was available."""
        from src.services.prediction_client import get_feed_forecast_from_prediction_service

        now = self._utc_now()
        local_tz = self._local_tz()
        seen_keys: set = set()
        weather_ok_barns: set = set()
        feed_ok_locations: set = set()

        for barn in self.db.get_all_barns():
            barn_id = barn.get("id") or barn.get("barn_id")
            if not barn_id:
                continue

            heat_cfg = self._rule_config("heat_stress")
            low_cfg = self._rule_config("low_feed")
            spoil_cfg = self._rule_config("spoilage_risk")
            cancel_cfg = self._rule_config("cancel_feeding_suggestion")

            heat_on = heat_cfg.get("enabled", True) and heat_cfg.get("prediction_enabled", True)
            low_on = low_cfg.get("enabled", True) and low_cfg.get("prediction_enabled", True)
            spoil_on = spoil_cfg.get("enabled", True) and spoil_cfg.get("prediction_enabled", True)
            cancel_on = cancel_cfg.get("enabled", True)

            heat_horizon = self._as_int(heat_cfg.get("prediction_horizon_hours", 48), 48)
            low_horizon = self._as_int(low_cfg.get("prediction_horizon_hours", 24), 24)
            spoil_horizon = self._as_int(spoil_cfg.get("prediction_horizon_hours", 24), 24)

            # Weather forecast: shared by predicted heat and the spoilage temp-gate.
            wx_rows = self.db.get_weather_forecast(barn_id, hours=max(heat_horizon, spoil_horizon, 1))
            weather_samples = forecast.thi_timeline(wx_rows, "forecast_for")

            if heat_on and wx_rows:
                weather_ok_barns.add(barn_id)
                thi_warn = self._as_float(self.db.get_threshold_value("heat_stress_thi_threshold", barn_id=barn_id, default=HEAT_STRESS_THI_THRESHOLD), HEAT_STRESS_THI_THRESHOLD)
                thi_crit = self._as_float(self.db.get_threshold_value("severe_heat_thi_threshold", barn_id=barn_id, default=SEVERE_HEAT_THI_THRESHOLD), SEVERE_HEAT_THI_THRESHOLD)
                warn_min = self._as_int(self.db.get_threshold_value("heat_stress_duration_minutes", barn_id=barn_id, default=240), 240)
                crit_min = self._as_int(self.db.get_threshold_value("severe_heat_duration_minutes", barn_id=barn_id, default=360), 360)
                res = continuous.evaluate(
                    heat_stress_rule(thi_warn, thi_crit, warn_min, crit_min),
                    weather_samples,
                    now + timedelta(hours=heat_horizon),
                )
                if res.crossed and res.sample:
                    key = notify.dedupe_key("heat_stress", barn_id, None, "predicted")
                    seen_keys.add(key)
                    thi_val = res.sample.values.get("thi")
                    await self._emit_predicted(
                        {
                            "alert_type": "heat_stress",
                            "severity": res.severity,
                            "barn_id": barn_id,
                            "barn_name": barn.get("name"),
                            "feeding_location_id": None,
                            "location_name": None,
                            "predicted_for": res.sample.t,
                            "thi": round(thi_val, 1) if thi_val is not None else None,
                            "message": (
                                f"Heat stress forecast: THI is projected to reach {thi_val:.1f}."
                                if thi_val is not None
                                else "Heat stress forecast."
                            ),
                        },
                        key,
                    )

            if not (low_on or spoil_on or cancel_on):
                continue

            locations = self.db.get_feeding_locations_by_barn(barn_id)
            schedules = self.db.get_feeding_schedules(barn_id=barn_id, is_active=True)
            feed_horizon = max(low_horizon, spoil_horizon, 1)
            horizon_end = now + timedelta(hours=feed_horizon)
            now_local = now.astimezone(local_tz)

            for location in locations:
                fl_id = location.get("feeding_location_id")
                if not fl_id:
                    continue
                location_name = location.get("name")

                try:
                    data = await get_feed_forecast_from_prediction_service(
                        feeding_location_id=fl_id,
                        barn_id=barn_id,
                        forecast_hours=feed_horizon,
                        apply_local_shift=False,
                    )
                except Exception as e:
                    logger.warning(f"Feed forecast unavailable for location {fl_id}: {e}")
                    continue

                fc_list = ((data or {}).get("result") or {}).get("forecast") or []
                if not fc_list:
                    continue
                feed_ok_locations.add(fl_id)
                feed_samples = forecast.feed_timeline(fc_list, weather_samples)

                if low_on:
                    low_pct = self._as_float(self.db.get_threshold_value("low_feed_percent", barn_id=barn_id, feeding_location_id=fl_id, default=20), 20)
                    crit_pct = self._as_float(self.db.get_threshold_value("low_feed_critical_percent", barn_id=barn_id, feeding_location_id=fl_id, default=10), 10)
                    res = continuous.evaluate(low_feed_rule(low_pct, crit_pct), feed_samples, horizon_end)
                    if res.crossed and res.sample:
                        key = notify.dedupe_key("low_feed", barn_id, fl_id, "predicted")
                        seen_keys.add(key)
                        lvl = res.sample.values.get("feed_level_pct")
                        await self._emit_predicted(
                            {
                                "alert_type": "low_feed",
                                "severity": res.severity,
                                "barn_id": barn_id,
                                "barn_name": barn.get("name"),
                                "feeding_location_id": fl_id,
                                "location_name": location_name,
                                "predicted_for": res.sample.t,
                                "current_level": round(lvl, 1) if lvl is not None else None,
                                "threshold": low_pct,
                                "message": (
                                    f"Feed at {location_name} is projected to reach {lvl:.1f}%."
                                    if lvl is not None
                                    else f"Low feed projected at {location_name}."
                                ),
                            },
                            key,
                        )

                if spoil_on:
                    spoil_pct = self._as_float(self.db.get_threshold_value("spoilage_feed_percent", barn_id=barn_id, feeding_location_id=fl_id, default=70), 70)
                    stale_hours = self._as_int(self.db.get_threshold_value("spoilage_stale_hours", barn_id=barn_id, feeding_location_id=fl_id, default=8), 8)
                    temp_c = self._as_float(self.db.get_threshold_value("spoilage_temp_c", barn_id=barn_id, feeding_location_id=fl_id, default=25), 25)
                    res = continuous.evaluate(spoilage_rule(spoil_pct, stale_hours, temp_c), feed_samples, horizon_end)
                    if res.crossed and res.sample:
                        key = notify.dedupe_key("spoilage_risk", barn_id, fl_id, "predicted")
                        seen_keys.add(key)
                        await self._emit_predicted(
                            {
                                "alert_type": "spoilage_risk",
                                "severity": "warning",
                                "barn_id": barn_id,
                                "barn_name": barn.get("name"),
                                "feeding_location_id": fl_id,
                                "location_name": location_name,
                                "predicted_for": res.sample.t,
                                "message": (
                                    f"Spoilage risk at {location_name}: feed is projected to stay above "
                                    f"{spoil_pct:.0f}% and warm for {stale_hours}h+ — consider removing a scheduled feeding."
                                ),
                            },
                            key,
                        )

                if cancel_on:
                    high_pct = self._as_float(self.db.get_threshold_value("cancel_feed_high_percent", barn_id=barn_id, feeding_location_id=fl_id, default=80), 80)
                    lookahead = self._as_float(self.db.get_threshold_value("cancel_feed_lookahead_hours", barn_id=barn_id, feeding_location_id=fl_id, default=2), 2)
                    suggested = None
                    for schedule in schedules:
                        if schedule.get("feeding_location_id") != fl_id or not schedule.get("is_active"):
                            continue
                        for start_local in event_rules.upcoming_feeding_starts(schedule, now_local, lookahead):
                            start_utc = start_local.astimezone(ZoneInfo("UTC"))
                            lvl = forecast.nearest_level(feed_samples, start_utc)
                            if lvl is not None and lvl > high_pct:
                                suggested = (start_utc, lvl)
                                break
                        if suggested:
                            break
                    if suggested:
                        start_utc, lvl = suggested
                        key = notify.dedupe_key("cancel_feeding_suggestion", barn_id, fl_id, "predicted")
                        seen_keys.add(key)
                        await self._emit_predicted(
                            {
                                "alert_type": "cancel_feeding_suggestion",
                                "severity": "info",
                                "barn_id": barn_id,
                                "barn_name": barn.get("name"),
                                "feeding_location_id": fl_id,
                                "location_name": location_name,
                                "predicted_for": start_utc,
                                "predicted_level": round(lvl, 1),
                                "message": (
                                    f"A scheduled feeding at {location_name} may overfill the trough "
                                    f"(projected {lvl:.0f}% > {high_pct:.0f}%). Consider skipping it."
                                ),
                            },
                            key,
                        )

        self._reap_predicted(seen_keys, weather_ok_barns, feed_ok_locations)

    _FEED_PREDICT_RULES = {"low_feed", "spoilage_risk", "cancel_feeding_suggestion"}

    def _reap_predicted(self, seen_keys: set, weather_ok_barns: set, feed_ok_locations: set):
        """Resolve predicted alerts whose dedupe_key wasn't re-seen this cycle — but
        only when the data source for that rule was actually available, so a missing
        forecast never false-clears a standing prediction."""
        try:
            for row in self.db.get_active_predicted_alerts():
                key = row.get("dedupe_key")
                if not key or key in seen_keys:
                    continue
                atype = row.get("alert_type")
                if atype == "heat_stress":
                    available = row.get("barn_id") in weather_ok_barns
                elif atype in self._FEED_PREDICT_RULES:
                    available = row.get("feeding_location_id") in feed_ok_locations
                else:
                    available = False
                if available:
                    self.db.resolve_alert(row.get("alert_id"))
        except Exception as e:
            logger.error(f"Error reaping predicted alerts: {e}")
            traceback.print_exc()

    async def run(self):
        try:
            await self.check_heat_stress()
            await self.check_feed_level()
            await self.check_health()
            await self.check_predicted()

            deleted = self.db.delete_old_alerts(hours=ALERT_EXPIRY_HOURS)
            if deleted:
                logger.info(f"Deleted {deleted} expired alerts older than {ALERT_EXPIRY_HOURS} hours")
        except Exception as e:
            logger.error(f"Error in alert engine run: {e}")
            traceback.print_exc()
